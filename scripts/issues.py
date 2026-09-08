#!/usr/bin/env python3
"""
Issue/PR triage automation for ForgePair.

Redesign of upstream aider's scripts/issues.py, per SPEC.md section 5
and BUILD_PLAN.md Phase 3. The upstream bot's core flaw: when it found
duplicate crash reports (matched by exact title), it silently closed
the newer ones pointing at the oldest issue with that title -- with no
check that the oldest issue was ever actually fixed. Recurrence count
was discarded instead of used as a priority signal, and feature
requests got no equivalent automated triage help at all (they lived or
died entirely on a human manually applying labels).

What changed here:

1. Verify-before-redirect for duplicate bug reports. A new report is
   only closed as a duplicate if the canonical (oldest) issue in that
   group has evidence of being resolved (a linked closing commit/PR,
   or has itself been closed). If the canonical issue is still open and
   unresolved, new reports are NOT closed -- instead the group gets a
   report-count-driven severity escalation (the `high-impact` label),
   so recurring failures become MORE visible over time, not less.

2. Feature-request clustering. Open enhancement-labeled issues are
   clustered by text similarity (title + body, difflib -- no ML
   dependency, see design discussion) instead of getting zero automated
   triage help. Clusters above a size threshold get flagged with
   `needs-triage` and a comment linking the related issues, so a human
   can see "these five requests are probably the same ask" without
   reading the whole backlog.

3. Known-issues dashboard. A single pinned GitHub issue is
   rewritten each run with a ranked list (by report count) of the
   duplicate-crash groups and feature-request clusters found. Lets a
   user self-check before filing yet another duplicate.

4. report.py's crash-reporter UX is intentionally untouched -- it
   already requires explicit user confirmation before filing (verified
   directly, see ARCHITECTURE_REVIEW.md/report.py test coverage), so
   the redesign here is entirely on the triage side, not the reporting
   side.

Everything else (stale-issue labeling/closing, fixed-issue closing,
unlabeled-issue nudging) is carried over from upstream mostly as-is --
those mechanisms weren't identified as broken, just the duplicate-
handling and the total absence of feature-request triage.
"""

import argparse
import difflib
import os
import re
from collections import defaultdict
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

BOT_SUFFIX = """

Note: [A bot script](https://github.com/TVick64889/forgepair/blob/main/scripts/issues.py) made these updates to the issue.
"""  # noqa

STALE_COMMENT = (
    """I'm labeling this issue as stale because it has been open for 2 weeks with no activity. If there are no additional comments, I will close it in 7 days."""  # noqa
    + BOT_SUFFIX
)

CLOSE_STALE_COMMENT = (
    """I'm closing this issue because it has been stalled for 3 weeks with no activity. Feel free to add a comment here and we can re-open it. Or feel free to file a new issue at any time."""  # noqa
    + BOT_SUFFIX
)

CLOSE_FIXED_ENHANCEMENT_COMMENT = (
    """I'm closing this enhancement request since it has been marked as 'fixed' for over """
    """3 weeks. The requested feature should now be available in recent versions of ForgePair.\n\n"""  # noqa
    """If you find that this enhancement is still needed, please feel free to reopen this """
    """issue or create a new one.""" + BOT_SUFFIX
)

CLOSE_FIXED_BUG_COMMENT = (
    """I'm closing this bug report since it has been marked as 'fixed' for over """
    """3 weeks. This issue should be resolved in recent versions of ForgePair.\n\n"""
    """If you find that this bug is still present, please feel free to reopen this """
    """issue or create a new one with steps to reproduce.""" + BOT_SUFFIX
)

DUPLICATE_COMMENT_RESOLVED = (
    """Thanks for trying ForgePair and filing this issue.

This looks like a duplicate of #{oldest_issue_number}, which has been resolved. Please see the comments there for more information, and feel free to reopen if you're still seeing this.

I'm going to close this issue for now. But please let me know if you think this is actually a distinct issue and I will reopen this issue."""  # noqa
    + BOT_SUFFIX
)

HIGH_IMPACT_COMMENT = (
    """This looks related to #{oldest_issue_number} and {other_count} other open report(s) of the same underlying issue ({total_count} total reports).

Since the original issue is still open and doesn't have a linked fix yet, I'm not closing this as a duplicate -- instead I've flagged the group as high-impact given how many independent reports it has. See #{oldest_issue_number} for the main discussion thread."""  # noqa
    + BOT_SUFFIX
)

FEATURE_CLUSTER_COMMENT_TEMPLATE = (
    """This looks similar to the following other open request(s), which may be asking for the same or related functionality:

{related_list}

Flagging for maintainer triage to check whether these should be consolidated."""  # noqa
    + BOT_SUFFIX
)

# GitHub API configuration
GITHUB_API_URL = "https://api.github.com"
REPO_OWNER = os.getenv("GITHUB_REPOSITORY_OWNER", "TVick64889")
REPO_NAME = os.getenv("GITHUB_REPOSITORY_NAME", "forgepair")
TOKEN = os.getenv("GITHUB_TOKEN")

HIGH_IMPACT_THRESHOLD = 3  # number of reports in a group before flagging high-impact
FEATURE_CLUSTER_SIMILARITY_THRESHOLD = 0.6  # difflib ratio, 0-1
FEATURE_CLUSTER_MIN_SIZE = 2  # minimum cluster size worth flagging
KNOWN_ISSUES_DASHBOARD_TITLE = "Known issues (auto-generated, do not edit)"

headers = {"Authorization": f"token {TOKEN}", "Accept": "application/vnd.github.v3+json"}


def has_been_reopened(issue_number):
    timeline_url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/timeline"
    response = requests.get(timeline_url, headers=headers)
    response.raise_for_status()
    events = response.json()
    return any(event["event"] == "reopened" for event in events if "event" in event)


def get_issues(state="open"):
    issues = []
    page = 1
    per_page = 100

    response = requests.get(
        f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues",
        headers=headers,
        params={"state": state, "per_page": 1},
    )
    response.raise_for_status()
    link_header = response.headers.get("Link", "")
    if 'rel="last"' in link_header:
        total_pages = int(link_header.split("page=")[-1].split(">")[0])
    else:
        total_pages = 1

    with tqdm(total=total_pages, desc="Collecting issues", unit="page") as pbar:
        while True:
            response = requests.get(
                f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues",
                headers=headers,
                params={"state": state, "page": page, "per_page": per_page},
            )
            response.raise_for_status()
            page_issues = response.json()
            if not page_issues:
                break
            issues.extend(page_issues)
            page += 1
            pbar.update(1)
    return issues


def is_pull_request(issue):
    return "pull_request" in issue


def issue_has_linked_closing_reference(issue_number):
    """
    Return True if there's evidence this issue was actually resolved:
    a 'closed' event via a linked commit/PR (cross_referenced by a merged
    PR, or a 'closed' timeline event with a commit_id), OR the issue is
    simply closed with state_reason 'completed'.

    This is the verify-before-redirect check: an issue closed as
    'not_planned' or with no commit reference is NOT considered
    resolved for triage purposes -- we don't want to redirect new
    reports into a hole that was closed without actually being fixed.
    """
    url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    issue = response.json()

    if issue["state"] != "closed":
        return False

    if issue.get("state_reason") == "completed":
        return True

    timeline_url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/timeline"
    response = requests.get(timeline_url, headers=headers)
    response.raise_for_status()
    events = response.json()

    for event in events:
        if event.get("event") == "closed" and event.get("commit_id"):
            return True
        if event.get("event") == "cross-referenced":
            source = event.get("source", {}).get("issue", {})
            if source.get("pull_request") and source.get("state") == "closed":
                if source.get("pull_request", {}).get("merged_at"):
                    return True

    return False


def group_issues_by_subject(issues):
    """Group open crash-report issues by exact title match (the existing
    'Uncaught X in Y line Z' auto-filed title pattern from report.py)."""
    grouped_issues = defaultdict(list)
    pattern = r"Uncaught .+ in .+ line \d+"
    for issue in issues:
        if is_pull_request(issue):
            continue
        if re.search(pattern, issue["title"]) and not has_been_reopened(issue["number"]):
            subject = issue["title"]
            grouped_issues[subject].append(issue)
    return grouped_issues


def find_oldest_issue(subject, all_issues):
    oldest_issue = None
    oldest_date = datetime.now(timezone.utc)

    for issue in all_issues:
        if issue["title"] == subject and not has_been_reopened(issue["number"]):
            created_at = datetime.strptime(issue["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            if created_at < oldest_date:
                oldest_date = created_at
                oldest_issue = issue

    return oldest_issue


def add_label(issue_number, label):
    url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}"
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    existing = [label_obj["name"] for label_obj in response.json()["labels"]]
    if label in existing:
        return
    response = requests.patch(url, headers=headers, json={"labels": existing + [label]})
    response.raise_for_status()


def post_comment(issue_number, body):
    comment_url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/comments"
    response = requests.post(comment_url, headers=headers, json={"body": body})
    response.raise_for_status()


def close_issue(issue_number):
    url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}"
    response = requests.patch(url, headers=headers, json={"state": "closed"})
    response.raise_for_status()


def comment_and_close_duplicate(issue, oldest_issue):
    if "priority" in [label["name"] for label in issue["labels"]]:
        print(f"  - Skipping priority issue #{issue['number']}")
        return

    comment_body = DUPLICATE_COMMENT_RESOLVED.format(oldest_issue_number=oldest_issue["number"])
    post_comment(issue["number"], comment_body)
    close_issue(issue["number"])
    print(
        f"  - Verified #{oldest_issue['number']} was resolved -- closed duplicate"
        f" #{issue['number']}"
    )


def escalate_high_impact(subject, issues, oldest_issue, auto_yes):
    """
    Verify-before-redirect: the canonical issue is still unresolved, so
    don't close the new reports. Instead escalate visibility by report
    count -- this is the core fix over upstream's dedup-and-silently-
    close behavior.
    """
    related_issues = set(issue["number"] for issue in issues)
    related_issues.add(oldest_issue["number"])
    total_count = len(related_issues)

    if total_count < HIGH_IMPACT_THRESHOLD:
        print(
            f"  - {total_count} report(s) of '{subject}', below threshold "
            f"({HIGH_IMPACT_THRESHOLD}) -- leaving as-is, no escalation."
        )
        return None

    print(
        f"  - {total_count} reports of '{subject}', canonical issue #{oldest_issue['number']} "
        "still unresolved -- escalating as high-impact."
    )

    if not auto_yes:
        confirm = input("    Add high-impact label and comment? (y/n): ")
        if confirm.lower() != "y":
            print("    Skipping.")
            return None

    add_label(oldest_issue["number"], "high-impact")

    already_commented_recently = any(c for c in _get_recent_bot_comments(oldest_issue["number"]))
    if not already_commented_recently:
        other_count = total_count - 1
        post_comment(
            oldest_issue["number"],
            HIGH_IMPACT_COMMENT.format(
                oldest_issue_number=oldest_issue["number"],
                other_count=other_count,
                total_count=total_count,
            ),
        )

    return {
        "subject": subject,
        "canonical": oldest_issue["number"],
        "canonical_url": oldest_issue["html_url"],
        "report_count": total_count,
        "related": sorted(related_issues),
    }


def _get_recent_bot_comments(issue_number):
    comments_url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue_number}/comments"
    response = requests.get(comments_url, headers=headers)
    response.raise_for_status()
    comments = response.json()
    return [c for c in comments if "made these updates to the issue" in c.get("body", "")]


def handle_duplicate_issues(all_issues, auto_yes):
    """
    Redesigned duplicate handling: verify-before-redirect. Only close a
    new report as a duplicate if the canonical (oldest) issue in the
    group has actual evidence of resolution. Otherwise, escalate the
    group's visibility instead of silently closing into a possibly-
    still-broken hole.
    """
    open_issues = [issue for issue in all_issues if issue["state"] == "open"]
    grouped_open_issues = group_issues_by_subject(open_issues)

    high_impact_groups = []

    print("Looking for duplicate crash reports (skipping reopened issues)...")
    for subject, issues in grouped_open_issues.items():
        oldest_issue = find_oldest_issue(subject, all_issues)
        if not oldest_issue:
            continue

        related_issues = set(issue["number"] for issue in issues)
        related_issues.add(oldest_issue["number"])
        if len(related_issues) <= 1:
            continue

        print(f"\nIssue group: {subject}")
        print(f"Open reports: {len(issues)}, canonical: #{oldest_issue['number']}")

        if oldest_issue["state"] == "open":
            canonical_resolved = issue_has_linked_closing_reference(oldest_issue["number"])
        else:
            canonical_resolved = issue_has_linked_closing_reference(oldest_issue["number"])

        if canonical_resolved:
            print(
                f"  - Canonical #{oldest_issue['number']} confirmed resolved -- treating new"
                " reports as duplicates."
            )
            if not auto_yes:
                confirm = input("  Comment and close duplicate issues? (y/n): ")
                if confirm.lower() != "y":
                    print("  Skipping this group.")
                    continue
            for issue in issues:
                if issue["number"] != oldest_issue["number"]:
                    comment_and_close_duplicate(issue, oldest_issue)
        else:
            group_info = escalate_high_impact(subject, issues, oldest_issue, auto_yes)
            if group_info:
                high_impact_groups.append(group_info)

    return high_impact_groups


def cluster_feature_requests(all_issues):
    """
    Cluster open enhancement-labeled issues by title+body text
    similarity (difflib.SequenceMatcher -- no ML dependency, per design
    decision: this doesn't need to be sophisticated, just meaningfully
    better than 'no automated triage at all', which is the current
    state for feature requests upstream).
    """
    open_enhancements = [
        issue
        for issue in all_issues
        if issue["state"] == "open"
        and not is_pull_request(issue)
        and "enhancement" in [label["name"] for label in issue["labels"]]
    ]

    def issue_text(issue):
        return f"{issue['title']}\n{issue.get('body') or ''}"[:2000]

    clusters = []
    assigned = set()

    for i, issue_a in enumerate(open_enhancements):
        if issue_a["number"] in assigned:
            continue
        cluster = [issue_a]
        for issue_b in open_enhancements[i + 1 :]:
            if issue_b["number"] in assigned:
                continue
            ratio = difflib.SequenceMatcher(None, issue_text(issue_a), issue_text(issue_b)).ratio()
            if ratio >= FEATURE_CLUSTER_SIMILARITY_THRESHOLD:
                cluster.append(issue_b)

        if len(cluster) >= FEATURE_CLUSTER_MIN_SIZE:
            for issue in cluster:
                assigned.add(issue["number"])
            clusters.append(cluster)

    return clusters


def handle_feature_clusters(all_issues, auto_yes):
    print("\nLooking for similar open feature requests...")
    clusters = cluster_feature_requests(all_issues)

    if not clusters:
        print("No feature-request clusters found.")
        return []

    cluster_summaries = []

    for cluster in clusters:
        numbers = sorted(issue["number"] for issue in cluster)
        print(f"\nPossible related feature requests: {numbers}")
        for issue in cluster:
            print(f"  - #{issue['number']}: {issue['title']} {issue['html_url']}")

        if not auto_yes:
            confirm = input("  Flag these as related (needs-triage + comment)? (y/n): ")
            if confirm.lower() != "y":
                print("  Skipping this cluster.")
                continue

        for issue in cluster:
            already_flagged = any(_get_recent_bot_comments(issue["number"]))
            if already_flagged:
                continue
            others = [i for i in cluster if i["number"] != issue["number"]]
            related_list = "\n".join(f"- #{o['number']}: {o['title']}" for o in others)
            add_label(issue["number"], "needs-triage")
            post_comment(
                issue["number"],
                FEATURE_CLUSTER_COMMENT_TEMPLATE.format(related_list=related_list),
            )
            print(f"  - Flagged #{issue['number']} as needs-triage")

        cluster_summaries.append(
            {
                "numbers": numbers,
                "urls": [issue["html_url"] for issue in cluster],
                "titles": [issue["title"] for issue in cluster],
            }
        )

    return cluster_summaries


def find_or_create_dashboard_issue():
    open_issues = get_issues("all")
    for issue in open_issues:
        if issue["title"] == KNOWN_ISSUES_DASHBOARD_TITLE and not is_pull_request(issue):
            return issue["number"]

    url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues"
    response = requests.post(
        url,
        headers=headers,
        json={
            "title": KNOWN_ISSUES_DASHBOARD_TITLE,
            "body": "Initializing...",
            "labels": ["documentation"],
        },
    )
    response.raise_for_status()
    return response.json()["number"]


def update_known_issues_dashboard(high_impact_groups, feature_clusters, auto_yes):
    """
    Rewrite a single pinned issue with a ranked (by report count) list
    of known duplicate-crash groups and feature-request clusters, so
    users can self-check before filing yet another duplicate. Per
    design decision, this lives as a GitHub issue (not a repo file), to
    avoid interacting with branch protection / opening PRs for a
    bot-generated report.
    """
    print("\nUpdating known-issues dashboard...")

    lines = [
        (
            f"_Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by the"
            " automated triage bot (`scripts/issues.py`). Do not edit this issue directly -- it"
            " will be overwritten on the next run._"
        ),
        "",
        "## Recurring bug reports (ranked by report count)",
        "",
    ]

    if high_impact_groups:
        for group in sorted(high_impact_groups, key=lambda g: -g["report_count"]):
            lines.append(
                f"- **{group['report_count']} reports** — {group['subject']}"
                f" — canonical: {group['canonical_url']}"
                f" (related: {', '.join('#' + str(n) for n in group['related'])})"
            )
    else:
        lines.append("_None currently above the high-impact threshold._")

    lines += ["", "## Possibly-related feature requests", ""]

    if feature_clusters:
        for cluster in feature_clusters:
            titles = "; ".join(cluster["titles"])
            numbers = ", ".join("#" + str(n) for n in cluster["numbers"])
            lines.append(f"- {numbers} — {titles}")
    else:
        lines.append("_None currently flagged._")

    body = "\n".join(lines)

    dashboard_number = find_or_create_dashboard_issue()

    if not auto_yes:
        confirm = input(f"  Overwrite dashboard issue #{dashboard_number}? (y/n): ")
        if confirm.lower() != "y":
            print("  Skipping dashboard update.")
            return

    url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{dashboard_number}"
    response = requests.patch(url, headers=headers, json={"body": body, "state": "open"})
    response.raise_for_status()
    print(f"  Updated dashboard issue #{dashboard_number}")


def find_unlabeled_with_maintainer_comments(issues, maintainer_logins):
    unlabeled_issues = []
    for issue in issues:
        if is_pull_request(issue):
            continue

        if not issue["labels"] and issue["state"] == "open":
            comments_url = (
                f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}/comments"
            )
            response = requests.get(comments_url, headers=headers)
            response.raise_for_status()
            comments = response.json()

            if any(comment["user"]["login"] in maintainer_logins for comment in comments):
                unlabeled_issues.append(issue)
    return unlabeled_issues


def handle_unlabeled_issues(all_issues, auto_yes, maintainer_logins):
    print("\nFinding unlabeled issues with maintainer comments...")
    unlabeled_issues = [
        issue
        for issue in find_unlabeled_with_maintainer_comments(all_issues, maintainer_logins)
        if "priority" not in [label["name"] for label in issue["labels"]]
    ]

    if not unlabeled_issues:
        print("No unlabeled issues with maintainer comments found.")
        return

    print(f"\nFound {len(unlabeled_issues)} unlabeled issues with maintainer comments:")
    for issue in unlabeled_issues:
        print(f"  - #{issue['number']}: {issue['title']} {issue['html_url']}")

    if not auto_yes:
        confirm = input("\nDo you want to add the 'question' label to these issues? (y/n): ")
        if confirm.lower() != "y":
            print("Skipping labeling.")
            return

    print("\nAdding 'question' label to issues...")
    for issue in unlabeled_issues:
        add_label(issue["number"], "question")
        print(f"  - Added 'question' label to #{issue['number']}")


def handle_stale_issues(all_issues, auto_yes):
    print("\nChecking for stale question issues...")

    for issue in all_issues:
        labels = [label["name"] for label in issue["labels"]]
        if (
            issue["state"] != "open"
            or "question" not in labels
            or "stale" in labels
            or "priority" in labels
            or has_been_reopened(issue["number"])
        ):
            continue

        latest_activity = datetime.strptime(issue["updated_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        days_inactive = (datetime.now(timezone.utc) - latest_activity).days
        if days_inactive >= 14:
            print(f"\nStale issue found: #{issue['number']}: {issue['title']}\n{issue['html_url']}")
            print(f"  No activity for {days_inactive} days")

            if not auto_yes:
                confirm = input("Add stale label and comment? (y/n): ")
                if confirm.lower() != "y":
                    print("Skipping this issue.")
                    continue

            post_comment(issue["number"], STALE_COMMENT)
            add_label(issue["number"], "stale")
            print(f"  Added stale label and comment to #{issue['number']}")


def handle_stale_closing(all_issues, auto_yes):
    print("\nChecking for issues to close or unstale...")

    for issue in all_issues:
        labels = [label["name"] for label in issue["labels"]]
        if issue["state"] != "open" or "stale" not in labels or "priority" in labels:
            continue

        timeline_url = (
            f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}/timeline"
        )
        response = requests.get(timeline_url, headers=headers)
        response.raise_for_status()
        events = response.json()

        stale_events = [
            event
            for event in events
            if event.get("event") == "labeled" and event.get("label", {}).get("name") == "stale"
        ]

        if not stale_events:
            continue

        latest_stale = datetime.strptime(
            stale_events[-1]["created_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)

        comments_url = (
            f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}/comments"
        )
        response = requests.get(comments_url, headers=headers)
        response.raise_for_status()
        comments = response.json()

        new_comments = [
            comment
            for comment in comments
            if datetime.strptime(comment["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc
            )
            > latest_stale
        ]

        if new_comments:
            print(f"\nFound new activity on stale issue #{issue['number']}: {issue['title']}")
            print(f"  {len(new_comments)} new comments since stale label")

            if not auto_yes:
                confirm = input("Remove stale label? (y/n): ")
                if confirm.lower() != "y":
                    print("Skipping this issue.")
                    continue

            url = f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}"
            response = requests.patch(url, headers=headers, json={"labels": ["question"]})
            response.raise_for_status()
            print(f"  Removed stale label from #{issue['number']}")
        else:
            days_stale = (datetime.now(timezone.utc) - latest_stale).days
            if days_stale >= 7:
                print(f"\nStale issue ready for closing #{issue['number']}: {issue['title']}")
                print(f"  No activity for {days_stale} days since stale label")

                if not auto_yes:
                    confirm = input("Close this issue? (y/n): ")
                    if confirm.lower() != "y":
                        print("Skipping this issue.")
                        continue

                post_comment(issue["number"], CLOSE_STALE_COMMENT)
                close_issue(issue["number"])
                print(f"  Closed issue #{issue['number']}")


def handle_fixed_issues(all_issues, auto_yes):
    print("\nChecking for fixed enhancement and bug issues to close...")

    for issue in all_issues:
        labels = [label["name"] for label in issue["labels"]]
        if issue["state"] != "open" or "fixed" not in labels or "priority" in labels:
            continue

        is_enhancement = "enhancement" in labels
        is_bug = "bug" in labels
        if not (is_enhancement or is_bug):
            continue

        timeline_url = (
            f"{GITHUB_API_URL}/repos/{REPO_OWNER}/{REPO_NAME}/issues/{issue['number']}/timeline"
        )
        response = requests.get(timeline_url, headers=headers)
        response.raise_for_status()
        events = response.json()

        fixed_events = [
            event
            for event in events
            if event.get("event") == "labeled" and event.get("label", {}).get("name") == "fixed"
        ]

        if not fixed_events:
            continue

        latest_fixed = datetime.strptime(
            fixed_events[-1]["created_at"], "%Y-%m-%dT%H:%M:%SZ"
        ).replace(tzinfo=timezone.utc)
        days_fixed = (datetime.now(timezone.utc) - latest_fixed).days

        if days_fixed >= 21:
            issue_type = "enhancement" if is_enhancement else "bug"
            print(f"\nFixed {issue_type} ready for closing #{issue['number']}: {issue['title']}")
            print(f"  Has been marked fixed for {days_fixed} days")

            if not auto_yes:
                confirm = input("Close this issue? (y/n): ")
                if confirm.lower() != "y":
                    print("Skipping this issue.")
                    continue

            comment = CLOSE_FIXED_ENHANCEMENT_COMMENT if is_enhancement else CLOSE_FIXED_BUG_COMMENT
            post_comment(issue["number"], comment)
            close_issue(issue["number"])
            print(f"  Closed issue #{issue['number']}")


def main():
    parser = argparse.ArgumentParser(description="ForgePair issue/PR triage automation")
    parser.add_argument(
        "--yes", action="store_true", help="Automatically apply actions without prompting"
    )
    parser.add_argument(
        "--maintainer-logins",
        default="TVick64889",
        help="Comma-separated GitHub usernames whose comments trigger unlabeled-issue nudging",
    )
    args = parser.parse_args()

    if not TOKEN:
        print("Error: Missing GITHUB_TOKEN environment variable. Please check your .env file.")
        return

    maintainer_logins = set(args.maintainer_logins.split(","))

    all_issues = get_issues("all")

    handle_unlabeled_issues(all_issues, args.yes, maintainer_logins)
    handle_stale_issues(all_issues, args.yes)
    handle_stale_closing(all_issues, args.yes)
    high_impact_groups = handle_duplicate_issues(all_issues, args.yes)
    feature_clusters = handle_feature_clusters(all_issues, args.yes)
    handle_fixed_issues(all_issues, args.yes)
    update_known_issues_dashboard(high_impact_groups, feature_clusters, args.yes)


if __name__ == "__main__":
    main()

"""
Staff roles, as Django groups. Created/updated automatically after "migrate".

A Django GROUP is a named bundle of permissions. Put a staff account in a group
(admin > Users > Groups) and it gets exactly those permissions. To change what
a role may do, edit ROLE_PERMISSIONS below and run "python manage.py migrate".

    Verification Officer  - sees applicant personal data; ticks the document
                            checklist; records/verifies EMD receipts; activates,
                            rejects or suspends applicants; may reveal a full
                            Aadhaar/PAN (every reveal is written to the audit log).
                            Cannot touch quarters or auctions.

    Auction Admin         - imports the quarter Excel, edits auction timings,
                            closes auctions, sees results by anonymous code.
                            Sees NO applicant personal data.

Superusers have every permission. Only they can see the Participation table
(the link between a real applicant and "Bidder N").
"""

ROLE_PERMISSIONS = {
    "Verification Officer": [
        ("applications", "applicant", ["view", "change", "verify_applicant", "reveal_identity_numbers"]),
        ("applications", "quarterapplication", ["view", "change"]),
        ("applications", "documentcheck", ["view", "change"]),
        ("applications", "documentchecklistitem", ["view"]),
        ("applications", "auditlog", ["view"]),
        ("auctions", "quarter", ["view"]),
    ],
    "Auction Admin": [
        ("auctions", "quarter", ["view", "add", "change"]),
        ("auctions", "auction", ["view", "change"]),
        ("auctions", "bid", ["view"]),
        ("applications", "documentchecklistitem", ["view", "add", "change"]),
    ],
}

CUSTOM_CODENAMES = {"verify_applicant", "reveal_identity_numbers"}


def setup_groups(**kwargs):
    from django.contrib.auth.models import Group, Permission

    for group_name, entries in ROLE_PERMISSIONS.items():
        group, _ = Group.objects.get_or_create(name=group_name)
        perms = []
        for app_label, model, actions in entries:
            for action in actions:
                codename = action if action in CUSTOM_CODENAMES else f"{action}_{model}"
                perm = Permission.objects.filter(content_type__app_label=app_label,
                                                 content_type__model=model, codename=codename).first()
                if perm:
                    perms.append(perm)
        group.permissions.set(perms)

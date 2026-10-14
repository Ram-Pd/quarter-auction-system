"""
Fill the document checklist with the PLACEHOLDER items from Change Request #3
(open question 8: the official list is still to be confirmed). Edit them later
in the admin: Applications and verification > Document checklist items.
"""
from django.db import migrations

ITEMS = [
    # (order, name, description, required)
    (1, "Identity proof (Aadhaar)", "Original Aadhaar card seen; number matches the application.", True),
    (2, "PAN card", "Original PAN card seen; number matches the application.", True),
    (3, "Address proof", "Any accepted address proof matching the application address.", True),
    (4, "Photograph", "Recent passport-size photograph.", True),
    (5, "Signed application form", "The emailed Application Form, printed and signed.", True),
    (6, "Other", "Any other document the office asks for.", False),
]


def add_items(apps, schema_editor):
    Item = apps.get_model("applications", "DocumentChecklistItem")
    for order, name, description, required in ITEMS:
        Item.objects.get_or_create(name=name, defaults={"order": order, "description": description,
                                                        "required": required})


def remove_items(apps, schema_editor):
    Item = apps.get_model("applications", "DocumentChecklistItem")
    Item.objects.filter(name__in=[name for _, name, _, _ in ITEMS], checks__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("applications", "0002_initial")]
    operations = [migrations.RunPython(add_items, remove_items)]

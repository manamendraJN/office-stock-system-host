from django.db import migrations


CATEGORIES = (
    ('Plantation Operations', 'Plantation, field, and crop production expenses.'),
    ('Office Supplies', 'Office stationery and administrative supplies.'),
    ('Travel and Conveyance', 'Business travel, transport, and conveyance.'),
    ('Utilities', 'Electricity, water, telephone, and internet.'),
    ('Repairs and Maintenance', 'Building, equipment, and vehicle maintenance.'),
    ('Staff Welfare', 'Staff welfare and employee-related expenses.'),
    ('Export and Freight', 'Export handling, freight, and logistics.'),
    ('Professional Fees', 'Legal, accounting, consulting, and other professional fees.'),
    ('General Expenses', 'Other approved business expenses.'),
)


def create_categories(apps, schema_editor):
    category = apps.get_model('vouchers', 'ExpenseCategory')
    category.objects.using(schema_editor.connection.alias).bulk_create(
        [category(name=name, description=description) for name, description in CATEGORIES],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [('vouchers', '0001_initial')]
    operations = [migrations.RunPython(create_categories, migrations.RunPython.noop)]

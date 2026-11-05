from django.db import migrations, models


def copy_company_name_to_system_display_name(apps, schema_editor):
    Setting = apps.get_model('core', 'Setting')
    for setting in Setting.objects.all():
        setting.system_display_name = setting.company_name or 'Office Stock'
        setting.save(update_fields=['system_display_name'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_setting_branding_controls'),
    ]

    operations = [
        migrations.AddField(
            model_name='setting',
            name='system_display_name',
            field=models.CharField(default='Office Stock', max_length=120),
        ),
        migrations.RunPython(copy_company_name_to_system_display_name, migrations.RunPython.noop),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_setting_payment_voucher_module_enabled_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='setting',
            name='company_logo',
            field=models.FileField(blank=True, default='', upload_to='company/'),
        ),
    ]

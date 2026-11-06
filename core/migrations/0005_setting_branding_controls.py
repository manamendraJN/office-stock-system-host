from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_setting_company_logo'),
    ]

    operations = [
        migrations.AddField(
            model_name='setting',
            name='login_logo_alignment',
            field=models.CharField(choices=[('left', 'Left'), ('center', 'Center'), ('right', 'Right')], default='center', max_length=10),
        ),
        migrations.AddField(
            model_name='setting',
            name='login_logo_offset_x',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='setting',
            name='login_logo_offset_y',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='setting',
            name='login_logo_size',
            field=models.PositiveIntegerField(default=128),
        ),
        migrations.AddField(
            model_name='setting',
            name='show_company_name_login',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='setting',
            name='show_company_name_system',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='setting',
            name='system_logo_alignment',
            field=models.CharField(choices=[('left', 'Left'), ('center', 'Center'), ('right', 'Right')], default='center', max_length=10),
        ),
        migrations.AddField(
            model_name='setting',
            name='system_logo_offset_x',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='setting',
            name='system_logo_offset_y',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='setting',
            name='system_logo_size',
            field=models.PositiveIntegerField(default=32),
        ),
    ]

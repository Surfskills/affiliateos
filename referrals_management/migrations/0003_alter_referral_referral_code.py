# Generated by Django 5.2 on 2025-05-22 08:41

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('referrals_management', '0002_alter_referral_product_name_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='referral',
            name='referral_code',
            field=models.CharField(blank=True, db_index=True, max_length=50, null=True),
        ),
    ]

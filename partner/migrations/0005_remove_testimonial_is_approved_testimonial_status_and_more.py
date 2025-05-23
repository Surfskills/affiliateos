# Generated by Django 5.2 on 2025-05-05 07:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('partner', '0004_alter_product_options_alter_testimonial_options_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='testimonial',
            name='is_approved',
        ),
        migrations.AddField(
            model_name='testimonial',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('approved', 'Approved'), ('rejected', 'Rejected')], default='pending', max_length=10),
        ),
        migrations.AlterField(
            model_name='partnerprofile',
            name='selected_products',
            field=models.ManyToManyField(related_name='partners', to='partner.product'),
        ),
        migrations.AlterField(
            model_name='testimonial',
            name='image',
            field=models.ImageField(blank=True, null=True, upload_to='testimonials/images/'),
        ),
        migrations.AlterField(
            model_name='testimonial',
            name='video',
            field=models.FileField(blank=True, null=True, upload_to='testimonials/videos/'),
        ),
    ]

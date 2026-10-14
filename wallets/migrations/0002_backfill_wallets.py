from django.db import migrations


def backfill_wallets(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    Wallet = apps.get_model("wallets", "Wallet")
    Wallet.objects.bulk_create(
        [Wallet(user_id=pk) for pk in User.objects.filter(wallet__isnull=True).values_list("pk", flat=True)]
    )


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_wallets, migrations.RunPython.noop),
    ]
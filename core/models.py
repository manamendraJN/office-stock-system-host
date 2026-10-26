import contextvars

from django.conf import settings
from django.db import IntegrityError, models, transaction
from django.db.models import F


class AppendOnlyQuerySet(models.QuerySet):
    """Rows can be added but never changed or removed through normal code.

    The original blocked update/delete at the model level. The few intentional exceptions
    (clearing an audit date range, the 30-day stock cleanup) call `unsafe_delete()` by name.
    """
    message = 'These rows cannot be changed or deleted.'

    def update(self, **kwargs):
        raise RuntimeError(self.message)

    def delete(self):
        raise RuntimeError(self.message)

    def bulk_update(self, objs, fields, batch_size=None):
        raise RuntimeError(self.message)

    def unsafe_delete(self):
        """Deliberate maintenance path. Returns the number of rows removed. Uses a raw DELETE so large
        clean-ups do not load every row into memory."""
        return self._raw_delete(using=self.db)


class AppendOnlyModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise RuntimeError(self.objects_message)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RuntimeError(self.objects_message)

    objects_message = 'These rows cannot be changed or deleted.'


_SETTING_CACHE = contextvars.ContextVar('setting_cache', default=None)


class Setting(models.Model):
    """The single settings row (key 'app')."""
    key = models.CharField(max_length=20, default='app', unique=True)
    branch_module_enabled = models.BooleanField(default=False)
    audit_logging_enabled = models.BooleanField(default=True)
    stock_retention_lock_until = models.DateTimeField(null=True, blank=True)
    company_name = models.CharField(max_length=120, default='Our Company')
    # Petty cash at or below this amount is flagged as low (Rs.). Changed by users who may configure petty cash.
    petty_cash_low_level = models.DecimalField(max_digits=12, decimal_places=2, default=2000)
    # Set once the default roles have been created, so deleted roles are never re-created.
    default_roles_seeded = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get(cls):
        """The settings row. Inside a web request it is read from the database once and reused for the rest of that
        request. Outside a request, or after a save, it is always read fresh."""
        cache = _SETTING_CACHE.get()
        if cache is not None and 'obj' in cache:
            return cache['obj']
        obj = cls._fetch()
        if cache is not None:
            cache['obj'] = obj
        return obj

    @classmethod
    def _fetch(cls):
        obj = cls.objects.filter(key='app').first()
        if obj:
            return obj
        try:
            with transaction.atomic():
                return cls.objects.create(key='app')
        except IntegrityError:
            return cls.objects.get(key='app')

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        cache = _SETTING_CACHE.get()
        if cache is not None:
            cache['obj'] = self

    def __str__(self):
        return 'Settings'


class Counter(models.Model):
    """Atomic counters behind numbers such as ITM-0001 and REQ-2026-0001."""
    key = models.CharField(max_length=40, unique=True)
    seq = models.PositiveIntegerField(default=0)

    @classmethod
    def next(cls, key):
        with transaction.atomic():
            try:
                with transaction.atomic():
                    cls.objects.get_or_create(key=key)
            except IntegrityError:
                pass
            cls.objects.filter(key=key).update(seq=F('seq') + 1)
            return cls.objects.get(key=key).seq


class AuditLogQuerySet(AppendOnlyQuerySet):
    message = 'Audit log entries cannot be changed or deleted.'


class AuditLog(AppendOnlyModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    action = models.CharField(max_length=60, db_index=True)
    record_type = models.CharField(max_length=40, blank=True, default='')
    record_id = models.CharField(max_length=40, blank=True, default='')
    old_value = models.JSONField(null=True, blank=True)
    new_value = models.JSONField(null=True, blank=True)
    ip = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AuditLogQuerySet.as_manager()
    objects_message = 'Audit log entries cannot be changed or deleted.'

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['-created_at'], name='audit_created_idx')]

    @classmethod
    def clear_range(cls, start, end):
        """Super Admin's explicit "clear a date range". Returns how many entries were removed."""
        return cls.objects.filter(created_at__gte=start, created_at__lte=end).unsafe_delete()

    def __str__(self):
        return f'{self.action} @ {self.created_at:%Y-%m-%d %H:%M}'

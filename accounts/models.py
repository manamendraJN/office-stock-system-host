from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils import timezone

from core.constants import BRANCH_TYPES, choices
from core.permissions import ALL_PERMISSIONS, SIDES, SUPER_ADMIN_ROLE


class Branch(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=10, unique=True)
    type = models.CharField(max_length=10, choices=[(BRANCH_TYPES.MAIN, 'Main office'), (BRANCH_TYPES.BRANCH, 'Branch')],
                            default=BRANCH_TYPES.BRANCH)
    address = models.CharField(max_length=250, blank=True, default='')
    phone = models.CharField(max_length=40, blank=True, default='')
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['type', 'name']
        constraints = [
            # Only one main office, enforced by the database as well as by the rule.
            models.UniqueConstraint(fields=['type'], condition=models.Q(type=BRANCH_TYPES.MAIN), name='one_main_office'),
        ]

    def save(self, *args, **kwargs):
        self.code = (self.code or '').strip().upper()
        super().save(*args, **kwargs)

    @property
    def is_main(self):
        return self.type == BRANCH_TYPES.MAIN

    def __str__(self):
        return self.name


class Role(models.Model):
    """A named set of typical features. Super Admin is built in and not stored here."""
    key = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=40)
    name_key = models.CharField(max_length=40, unique=True)  # lower-case name, so "Cashier" and "cashier" clash
    description = models.CharField(max_length=200, blank=True, default='')
    side = models.CharField(max_length=10, choices=[(SIDES.MAIN, 'Main office'), (SIDES.BRANCH, 'Branch')])
    permissions = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        from core.rules.role_rules import normalize_name
        self.name_key = normalize_name(self.name)
        self.permissions = [p for p in (self.permissions or []) if p in ALL_PERMISSIONS]
        super().save(*args, **kwargs)

    def as_def(self):
        return {'key': self.key, 'name': self.name, 'side': self.side, 'description': self.description,
                'permissions': list(self.permissions or [])}

    def __str__(self):
        return self.name


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password, **extra):
        if not email:
            raise ValueError('An email is required')
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save()
        return user


class User(AbstractBaseUser):
    name = models.CharField(max_length=120)
    email = models.EmailField(unique=True)
    # Key of a Role. Super Admin is the built-in 'super_admin'.
    role = models.CharField(max_length=40)
    # Ticked features. NULL on older accounts, which then use their role's typical set.
    permissions = models.JSONField(null=True, blank=True, default=None)
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT, related_name='users')
    active = models.BooleanField(default=True)
    failed_logins = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']
    objects = UserManager()

    class Meta:
        ordering = ['name']

    # Django's auth machinery reads is_active; the original field is called `active`.
    @property
    def is_active(self):
        return self.active

    def save(self, *args, **kwargs):
        self.email = (self.email or '').strip().lower()
        super().save(*args, **kwargs)

    @property
    def role_def(self):
        """This user's role (name, side, typical features), looked up fresh per request so
        edits to a role apply at once. None when the role has since vanished."""
        if not hasattr(self, '_role_def'):
            if self.role == SUPER_ADMIN_ROLE['key']:
                self._role_def = SUPER_ADMIN_ROLE
            else:
                r = Role.objects.filter(key=self.role).first()
                self._role_def = r.as_def() if r else None
        return self._role_def

    @role_def.setter
    def role_def(self, value):
        self._role_def = value

    @property
    def role_name(self):
        return (self.role_def or {}).get('name') or self.role

    @property
    def is_locked(self):
        return bool(self.locked_until and self.locked_until > timezone.now())

    def __str__(self):
        return f'{self.name} <{self.email}>'

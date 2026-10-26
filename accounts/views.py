import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts import services
from accounts.forms import (BranchForm, ChangePasswordForm, LoginForm, ResetPasswordForm, RoleForm, UserForm)
from accounts.models import Branch, Role, User
from accounts.roles import all_role_defs, find_role_def
from core.constants import BRANCH_TYPES, ROLES
from core.decorators import super_admin_required
from core.errors import ServiceError
from core.forms import apply_service_error
from core.permissions import ALL_PERMISSIONS, FEATURES, IMPLIES, SIDE_LABELS, SUPER_ADMIN_ROLE, UNSET, effective_permissions
from core.services.audit import client_ip

LOGIN_WINDOW = 15 * 60
LOGIN_LIMIT = 30  # attempts per address per 15 minutes, as in the original


def _rate_limited(request):
    key = f'login-attempts:{client_ip(request)}'
    cache.add(key, 0, LOGIN_WINDOW)
    try:
        return cache.incr(key) > LOGIN_LIMIT
    except ValueError:
        cache.set(key, 1, LOGIN_WINDOW)
        return False


def login_view(request):
    if request.user.is_authenticated:
        return redirect('core:dashboard')
    form = LoginForm(request.POST or None)
    if request.method == 'POST':
        if _rate_limited(request):
            form.add_error(None, 'Too many sign-in attempts. Please wait a few minutes and try again')
        elif form.is_valid():
            try:
                services.sign_in(request, form.cleaned_data['email'], form.cleaned_data['password'])
            except ServiceError as exc:
                form.add_error(None, exc.message)
            else:
                nxt = request.POST.get('next') or request.GET.get('next') or ''
                if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
                    return redirect(nxt)
                return redirect('core:dashboard')
    return render(request, 'accounts/login.html', {'form': form, 'next': request.GET.get('next', '')})


@require_POST
def logout_view(request):
    from django.contrib.auth import logout
    logout(request)
    return redirect('accounts:login')


@login_required
def change_password_view(request):
    form = ChangePasswordForm(request.POST or None, user=request.user)
    done = False
    if request.method == 'POST' and form.is_valid():
        try:
            services.change_password(request, form.cleaned_data['current_password'], form.cleaned_data['new_password'])
        except ServiceError as exc:
            apply_service_error(form, exc)
        else:
            # Changing the password rotates the session hash; keep this browser signed in.
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Your password has been changed.')
            return redirect('core:dashboard')
    return render(request, 'accounts/change_password.html', {'form': form, 'done': done})


# ------------------------------------------------------------------ users
def _permission_context(selected):
    return {'features': FEATURES, 'selected': list(selected), 'implies_json': json.dumps(IMPLIES)}


def _role_choices():
    out = []
    for d in all_role_defs():
        out.append({'key': d['key'], 'name': d['name'], 'side': d['side'], 'description': d.get('description', ''),
                    'permissions': list(d['permissions'])})
    return out


def _user_rows():
    roles = {d['key']: d for d in all_role_defs()}
    rows = []
    for u in User.objects.select_related('branch').order_by('name'):
        d = roles.get(u.role)
        perms = effective_permissions(u, d)
        rows.append({'u': u, 'role_name': d['name'] if d else u.role, 'perm_count': len(perms),
                     'full': u.role == ROLES.SUPER_ADMIN})
    return rows


@super_admin_required
def user_list(request):
    return render(request, 'accounts/user_list.html', {'rows': _user_rows()})


def _user_form_view(request, editing=None):
    form = UserForm(request.POST or None, editing=editing,
                    initial=None if editing is None else {'name': editing.name, 'email': editing.email,
                                                         'role': editing.role, 'branch': editing.branch_id})
    roles = _role_choices()
    if request.method == 'POST':
        selected = request.POST.getlist('permissions')
    elif editing is not None:
        selected = effective_permissions(editing, find_role_def(editing.role))
    else:
        selected = []
    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        # Super Admin always has everything, so ticks are only read for other roles.
        requested = UNSET if cd['role'] == ROLES.SUPER_ADMIN else [p for p in selected if p in ALL_PERMISSIONS]
        try:
            if editing is None:
                user = services.create_user(request, name=cd['name'], email=cd['email'], password=cd['password'], role=cd['role'],
                                            branch=cd['branch'], requested_permissions=requested)
                messages.success(request, 'User created')
            else:
                user = services.update_user(request, editing, requested_permissions=requested,
                                            changes={'name': cd['name'], 'email': cd['email'], 'role': cd['role'], 'branch': cd['branch']})
                messages.success(request, 'User updated')
            return redirect('accounts:user_list')
        except ServiceError as exc:
            apply_service_error(form, exc)
    branches = [{'id': b.pk, 'name': b.name, 'type': b.type} for b in form.fields['branch'].queryset]
    ctx = {'form': form, 'editing': editing, 'roles': roles, 'branches': branches,
           'current_role': (form['role'].value() or ''), 'current_branch': str(form['branch'].value() or ''),
           'role_missing': bool(form['role'].value()) and all(r['key'] != form['role'].value() for r in roles),
           'role_error': form['role'].errors, 'branch_error': form['branch'].errors,
           **_permission_context(selected)}
    return render(request, 'accounts/user_form.html', ctx)


@super_admin_required
def user_create(request):
    return _user_form_view(request)


@super_admin_required
def user_edit(request, pk):
    return _user_form_view(request, get_object_or_404(User, pk=pk))


@super_admin_required
def user_reset_password(request, pk):
    user = get_object_or_404(User, pk=pk)
    form = ResetPasswordForm(request.POST or None, user=user)
    if request.method == 'POST' and form.is_valid():
        try:
            services.update_user(request, user, password=form.cleaned_data['password'])
        except ServiceError as exc:
            apply_service_error(form, exc)
        else:
            messages.success(request, f'Password reset for {user.name}')
            return redirect('accounts:user_list')
    return render(request, 'accounts/user_reset_password.html', {'form': form, 'target': user})


@super_admin_required
@require_POST
def user_toggle_active(request, pk):
    user = get_object_or_404(User, pk=pk)
    want = not user.active
    try:
        services.update_user(request, user, changes={'active': want})
        messages.success(request, f'{user.name} {"enabled" if want else "disabled"}')
    except ServiceError as exc:
        messages.error(request, exc.message)
    return redirect('accounts:user_list')


# ------------------------------------------------------------------ roles
def _role_rows():
    counts = services.role_user_counts()
    rows = [{'key': SUPER_ADMIN_ROLE['key'], 'id': None, 'name': SUPER_ADMIN_ROLE['name'], 'description': SUPER_ADMIN_ROLE['description'],
             'side': SUPER_ADMIN_ROLE['side'], 'side_label': SIDE_LABELS[SUPER_ADMIN_ROLE['side']], 'built_in': True,
             'perm_count': len(SUPER_ADMIN_ROLE['permissions']), 'user_count': counts.get(SUPER_ADMIN_ROLE['key'], 0)}]
    for r in Role.objects.all():
        rows.append({'key': r.key, 'id': r.pk, 'name': r.name, 'description': r.description, 'side': r.side,
                     'side_label': SIDE_LABELS[r.side], 'built_in': False, 'perm_count': len(r.permissions or []),
                     'user_count': counts.get(r.key, 0)})
    return rows


@super_admin_required
def role_list(request):
    return render(request, 'accounts/role_list.html', {'rows': _role_rows()})


def _role_form_view(request, role=None):
    counts = services.role_user_counts()
    user_count = counts.get(role.key, 0) if role else 0
    side_locked = bool(role and user_count > 0)
    initial = {'name': role.name, 'description': role.description, 'side': role.side} if role else None
    form = RoleForm(request.POST or None, initial=initial)
    if side_locked:
        form.fields['side'].disabled = True
    selected = request.POST.getlist('permissions') if request.method == 'POST' else list(role.permissions) if role else []
    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        picked = [p for p in selected if p in ALL_PERMISSIONS]
        try:
            if role is None:
                services.create_role(request, name=cd['name'], description=cd['description'], side=cd['side'], permissions=picked)
                messages.success(request, 'Role created')
            else:
                from core.permissions import normalize_permissions
                changed = set(normalize_permissions(picked)) != set(role.permissions or [])
                _, updated = services.update_role(
                    request, role, name=cd['name'], description=cd['description'],
                    side=None if side_locked else cd['side'], permissions=picked,
                    apply_to_users=bool(request.POST.get('apply_to_users')) and changed)
                n = updated
                messages.success(request, f'Role updated, and {n} user{"" if n == 1 else "s"} given the new ticks' if n else 'Role updated')
            return redirect('accounts:role_list')
        except ServiceError as exc:
            apply_service_error(form, exc)
    return render(request, 'accounts/role_form.html', {
        'form': form, 'role': role, 'user_count': user_count, 'side_locked': side_locked,
        'current_side': form['side'].value() or '', 'role_perms_json': json.dumps(list(role.permissions) if role else []),
        'side_hint': f"{user_count} user{' has' if user_count == 1 else 's have'} this role, so this cannot be changed",
        **_permission_context(selected)})


@super_admin_required
def role_create(request):
    return _role_form_view(request)


@super_admin_required
def role_edit(request, pk):
    try:
        role = services.get_stored_role(pk)
    except ServiceError as exc:
        if exc.status == 404:
            raise Http404(exc.message)
        messages.error(request, exc.message)
        return redirect('accounts:role_list')
    return _role_form_view(request, role)


@super_admin_required
@require_POST
def role_delete(request, pk):
    try:
        role = services.get_stored_role(pk)
        services.delete_role(request, role)
        messages.success(request, f'Role "{role.name}" deleted')
    except ServiceError as exc:
        if exc.status == 404:
            raise Http404(exc.message)
        messages.error(request, exc.message)
    return redirect('accounts:role_list')


# ------------------------------------------------------------------ branches
@super_admin_required
def branch_list(request):
    from django.db.models import Count
    branches = Branch.objects.annotate(user_count=Count('users')).order_by('type', 'name')
    return render(request, 'accounts/branch_list.html', {'branches': branches})


def _branch_form_view(request, branch=None):
    initial = ({'name': branch.name, 'code': branch.code, 'address': branch.address, 'phone': branch.phone, 'active': branch.active}
               if branch else None)
    form = BranchForm(request.POST or None, initial=initial)
    is_main = bool(branch and branch.type == BRANCH_TYPES.MAIN)
    show_active = bool(branch and not is_main)
    if not show_active:
        del form.fields['active']
    if request.method == 'POST' and form.is_valid():
        cd = form.cleaned_data
        try:
            if branch is None:
                services.create_branch(request, name=cd['name'], code=cd['code'], address=cd['address'], phone=cd['phone'])
                messages.success(request, 'Branch added')
            else:
                changes = {'name': cd['name'], 'code': cd['code'], 'address': cd['address'], 'phone': cd['phone']}
                if show_active:
                    changes['active'] = cd['active']
                services.update_branch(request, branch, changes)
                messages.success(request, 'Branch updated')
            return redirect('accounts:branch_list')
        except ServiceError as exc:
            apply_service_error(form, exc)
    return render(request, 'accounts/branch_form.html', {'form': form, 'branch': branch, 'show_active': show_active})


@super_admin_required
def branch_create(request):
    return _branch_form_view(request)


@super_admin_required
def branch_edit(request, pk):
    return _branch_form_view(request, get_object_or_404(Branch, pk=pk))


@super_admin_required
@require_POST
def branch_delete(request, pk):
    branch = get_object_or_404(Branch, pk=pk)
    try:
        outcome = services.delete_branch(request, branch)
    except ServiceError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, 'Branch deleted' if outcome == 'deleted'
                         else 'This branch has users or history, so it was deactivated instead of deleted')
    return redirect('accounts:branch_list')

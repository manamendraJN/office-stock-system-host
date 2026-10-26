"""Shared builders for the Django tests."""
from datetime import date
from types import SimpleNamespace

from accounts.models import Branch, User
from accounts.roles import ensure_default_roles
from catalog.models import Category, Item, Supplier
from core.constants import BRANCH_TYPES, ROLES

PASSWORD = 'Str0ng-Passw0rd!'


def fake_request(user):
    """The services only need request.user and request.META."""
    return SimpleNamespace(user=user, META={'REMOTE_ADDR': '127.0.0.1'})


def make_world():
    """A main office, one branch, a Super Admin, a stock officer, a branch user, a category, a supplier and two items."""
    ensure_default_roles()
    main = Branch.objects.create(code='NUG', name='Main Office', type=BRANCH_TYPES.MAIN)
    kandy = Branch.objects.create(code='KDY', name='Kandy', type=BRANCH_TYPES.BRANCH)
    admin = User.objects.create_user(email='admin@example.test', password=PASSWORD, name='Admin', role=ROLES.SUPER_ADMIN, branch=main)
    officer = User.objects.create_user(email='officer@example.test', password=PASSWORD, name='Officer', role=ROLES.STOCK_OFFICER, branch=main)
    branch_user = User.objects.create_user(
        email='kandy@example.test', password=PASSWORD, name='Kandy User', role=ROLES.BRANCH_USER, branch=kandy,
        permissions=['items.view', 'stock.view', 'requests.create', 'dispatches.receive'])
    cat = Category.objects.create(name='Paper')
    supplier = Supplier.objects.create(name='Acme')
    paper = Item.objects.create(code='PAP-1', name='Paper', category=cat, unit='ream', min_stock=5)
    pen = Item.objects.create(code='PEN-1', name='Pen', category=cat, unit='box', min_stock=2)
    return SimpleNamespace(main=main, kandy=kandy, admin=admin, officer=officer, branch_user=branch_user,
                           cat=cat, supplier=supplier, paper=paper, pen=pen)


def receive_stock(w, item, quantity, cost='10.00'):
    """Buy and receive `quantity` of an item into the main office through the real services."""
    from inventory.services import purchases
    req = fake_request(w.officer)
    p = purchases.create_purchase(req, {'supplier': w.supplier, 'purchase_date': date.today(), 'invoice_ref': '', 'notes': '',
                                        'lines': [{'item': item, 'quantity_ordered': quantity, 'unit_cost': cost}]})
    line = p.lines.first()
    purchases.receive_purchase(req, p.pk, [{'line_id': line.pk, 'quantity': quantity}])
    return p

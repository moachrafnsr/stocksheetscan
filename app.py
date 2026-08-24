from datetime import datetime, timedelta
import io
import os
import uuid
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

app = Flask(__name__)
app.config['SECRET_KEY'] = 'stocksheet_secret_key_2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'


# --- MODÈLES DE LA BASE DE DONNÉES ---
class User(UserMixin, db.Model):
  id = db.Column(db.Integer, primary_key=True)
  username = db.Column(db.String(150), unique=True, nullable=False)
  password = db.Column(db.String(150), nullable=False)
  is_admin = db.Column(db.Boolean, default=False)
  expiry_date = db.Column(db.DateTime, nullable=True)

  company_name = db.Column(db.String(150), nullable=True)
  logo_filename = db.Column(db.String(150), nullable=True)
  ice = db.Column(db.String(50), nullable=True)
  if_tax = db.Column(db.String(50), nullable=True)
  rc = db.Column(db.String(50), nullable=True)
  phone = db.Column(db.String(50), nullable=True)
  address = db.Column(db.String(250), nullable=True)
  email = db.Column(db.String(150), nullable=True)
  website = db.Column(db.String(150), nullable=True)
  currency = db.Column(db.String(10), default='DH')


class ActivationCode(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  code = db.Column(db.String(50), unique=True, nullable=False)
  duration_months = db.Column(db.Integer, nullable=False)
  is_used = db.Column(db.Boolean, default=False)
  used_by = db.Column(db.String(150), nullable=True)


class CommercialInventory(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  name = db.Column(db.String(150), nullable=False)
  phone = db.Column(db.String(50), nullable=True)
  zone = db.Column(db.String(100), nullable=True)
  user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class Product(db.Model):
  id = db.Column(db.Integer, primary_key=True)
  barcode = db.Column(db.String(100), nullable=False)
  name = db.Column(db.String(150), nullable=False)
  quantity = db.Column(db.Integer, nullable=False)
  price = db.Column(db.Float, nullable=False)
  inventory_type = db.Column(db.String(50), default='Principal')
  user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


@login_manager.user_loader
def load_user(user_id):
  return User.query.get(int(user_id))


with app.app_context():
  db.create_all()
  admin = User.query.filter_by(username='admin').first()
  if not admin:
    admin_user = User(
        username='admin', password='adminpassword', is_admin=True
    )
    db.session.add(admin_user)
    db.session.commit()


@app.route('/')
def index():
  return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
  if request.method == 'POST':
    username = request.form.get('username')
    password = request.form.get('password')

    user = User.query.filter_by(username=username).first()
    if user and user.password == password:
      login_user(user)
      if user.is_admin:
        return redirect(url_for('admin_dashboard'))
      else:
        return redirect(url_for('client_dashboard'))

    flash('Identifiants invalides.')
  return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
  if request.method == 'POST':
    username = request.form.get('username')
    password = request.form.get('password')

    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
      flash("Ce nom d'utilisateur existe déjà.")
      return redirect(url_for('register'))

    # 2 mois d'essai gratuit offerts à l'inscription (60 jours)
    free_expiry = datetime.utcnow() + timedelta(days=60)

    new_user = User(
        username=username,
        password=password,
        is_admin=False,
        expiry_date=free_expiry,
    )
    db.session.add(new_user)
    db.session.commit()
    login_user(new_user)
    flash(
        'Compte créé avec succès ! Profitez de vos 2 mois d’essai gratuit offerts'
        ' 🎉'
    )
    return redirect(url_for('client_dashboard'))

  return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
  logout_user()
  return redirect(url_for('index'))


# --- ROUTES ADMIN SUPERUSER ---
@app.route('/admin')
@login_required
def admin_dashboard():
  if not current_user.is_admin:
    return redirect(url_for('login'))
  codes = ActivationCode.query.all()
  clients = User.query.filter_by(is_admin=False).all()

  total_clients = len(clients)
  active_clients = sum(
      1 for c in clients if c.expiry_date and c.expiry_date > datetime.utcnow()
  )
  total_codes = len(codes)
  unused_codes = sum(1 for c in codes if not c.is_used)

  return render_template(
      'admin.html',
      codes=codes,
      clients=clients,
      now=datetime.utcnow(),
      total_clients=total_clients,
      active_clients=active_clients,
      total_codes=total_codes,
      unused_codes=unused_codes,
  )


@app.route('/admin/generate', methods=['POST'])
@login_required
def generate_code():
  if not current_user.is_admin:
    return redirect(url_for('login'))
  duration = int(request.form.get('duration'))
  unique_code = 'STK-' + str(uuid.uuid4()).upper()[:8]
  new_code = ActivationCode(
      code=unique_code, duration_months=duration, is_used=False, used_by='Aucun'
  )
  db.session.add(new_code)
  db.session.commit()
  flash(f'Code d’activation généré avec succès : {unique_code}')
  return redirect(url_for('admin_dashboard'))


@app.route('/admin/code/delete/<int:code_id>', methods=['POST'])
@login_required
def delete_code(code_id):
  if not current_user.is_admin:
    return redirect(url_for('login'))
  code_obj = ActivationCode.query.get_or_404(code_id)
  db.session.delete(code_obj)
  db.session.commit()
  flash('Code d’activation supprimé avec succès.')
  return redirect(url_for('admin_dashboard'))


@app.route('/admin/change_password', methods=['POST'])
@login_required
def admin_change_password():
  if not current_user.is_admin:
    return redirect(url_for('login'))
  new_pwd = request.form.get('new_password')
  if new_pwd:
    current_user.password = new_pwd
    db.session.commit()
    flash('Votre mot de passe administrateur a été mis à jour avec succès !')
  else:
    flash('Le mot de passe ne peut pas être vide.')
  return redirect(url_for('admin_dashboard'))


@app.route('/admin/client/update/<int:client_id>', methods=['POST'])
@login_required
def admin_update_client(client_id):
  if not current_user.is_admin:
    return redirect(url_for('login'))
  client = User.query.get_or_404(client_id)
  new_password = request.form.get('password')
  if new_password:
    client.password = new_password
    db.session.commit()
    flash(f"Mot de passe mis à jour pour {client.username}")
  return redirect(url_for('admin_dashboard'))


@app.route('/admin/client/suspend/<int:client_id>', methods=['POST'])
@login_required
def admin_suspend_client(client_id):
  if not current_user.is_admin:
    return redirect(url_for('login'))
  client = User.query.get_or_404(client_id)
  client.expiry_date = datetime.utcnow() - timedelta(days=1)
  db.session.commit()
  flash(f"Licence suspendue pour {client.username}")
  return redirect(url_for('admin_dashboard'))


@app.route('/admin/client/reactivate/<int:client_id>', methods=['POST'])
@login_required
def admin_reactivate_client(client_id):
  if not current_user.is_admin:
    return redirect(url_for('login'))
  client = User.query.get_or_404(client_id)
  client.expiry_date = datetime.utcnow() + timedelta(days=30)
  db.session.commit()
  flash(f"Licence réactivée pour 1 mois pour {client.username}")
  return redirect(url_for('admin_dashboard'))


@app.route('/admin/client/delete/<int:client_id>', methods=['POST'])
@login_required
def admin_delete_client(client_id):
  if not current_user.is_admin:
    return redirect(url_for('login'))
  client = User.query.get_or_404(client_id)
  Product.query.filter_by(user_id=client.id).delete()
  CommercialInventory.query.filter_by(user_id=client.id).delete()
  db.session.delete(client)
  db.session.commit()
  flash('Client et ses données supprimés avec succès.')
  return redirect(url_for('admin_dashboard'))


# --- ROUTES CLIENT ---
@app.route('/client')
@login_required
def client_dashboard():
  if current_user.is_admin:
    return redirect(url_for('admin_dashboard'))

  if current_user.expiry_date and current_user.expiry_date < datetime.utcnow():
    logout_user()
    flash('Votre abonnement a expiré ou a été suspendu par l’administrateur.')
    return redirect(url_for('login'))

  time_left_str = 'Inactif (Aucun abonnement)'
  if current_user.expiry_date:
    if current_user.expiry_date > datetime.utcnow():
      diff = current_user.expiry_date - datetime.utcnow()
      days = diff.days
      hours = diff.seconds // 3600
      time_left_str = f'{days} jours, {hours} heures restants'
    else:
      time_left_str = 'Abonnement expiré'

  active_tab = request.args.get('tab', 'Principal')
  commercials = CommercialInventory.query.filter_by(
      user_id=current_user.id
  ).all()
  products = Product.query.filter_by(
      user_id=current_user.id, inventory_type=active_tab
  ).all()

  current_commercial = None
  if active_tab.startswith('comm_'):
    comm_id = int(active_tab.split('_')[1])
    current_commercial = CommercialInventory.query.get(comm_id)

  currency = current_user.currency if current_user.currency else 'DH'

  return render_template(
      'client.html',
      products=products,
      time_left=time_left_str,
      active_tab=active_tab,
      commercials=commercials,
      current_commercial=current_commercial,
      currency=currency,
  )


@app.route('/client/settings', methods=['GET', 'POST'])
@login_required
def client_settings():
  if current_user.is_admin:
    return redirect(url_for('admin_dashboard'))

  if request.method == 'POST':
    code_text = request.form.get('activation_code')
    if code_text:
      activation_code = ActivationCode.query.filter_by(
          code=code_text, is_used=False
      ).first()
      if activation_code:
        base_date = (
            current_user.expiry_date
            if current_user.expiry_date and current_user.expiry_date > datetime.utcnow()
            else datetime.utcnow()
        )
        current_user.expiry_date = base_date + timedelta(
            days=30 * activation_code.duration_months
        )
        activation_code.is_used = True
        activation_code.used_by = current_user.username
        flash('Compte activé avec succès !')
      else:
        flash('Code d’activation invalide ou déjà utilisé.')

    current_user.company_name = request.form.get('company_name')
    current_user.ice = request.form.get('ice')
    current_user.if_tax = request.form.get('if_tax')
    current_user.rc = request.form.get('rc')
    current_user.phone = request.form.get('phone')
    current_user.address = request.form.get('address')
    current_user.email = request.form.get('email')
    current_user.website = request.form.get('website')
    current_user.currency = request.form.get('currency', 'DH')

    logo_file = request.files.get('logo')
    if logo_file and logo_file.filename != '':
      filename = f'logo_user_{current_user.id}_{logo_file.filename}'
      logo_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
      logo_file.save(logo_path)
      current_user.logo_filename = filename

    db.session.commit()
    flash('Paramètres de l’entreprise mis à jour avec succès !')

  time_left_str = 'Inactif'
  if current_user.expiry_date and current_user.expiry_date > datetime.utcnow():
    diff = current_user.expiry_date - datetime.utcnow()
    time_left_str = f'{diff.days} jours restants'

  return render_template('settings.html', time_left=time_left_str)


@app.route('/client/add_commercial', methods=['POST'])
@login_required
def add_commercial():
  if current_user.is_admin:
    return redirect(url_for('login'))
  name = request.form.get('name')
  phone = request.form.get('phone')
  zone = request.form.get('zone')

  new_comm = CommercialInventory(
      name=name, phone=phone, zone=zone, user_id=current_user.id
  )
  db.session.add(new_comm)
  db.session.commit()
  db.session.refresh(new_comm)
  return redirect(url_for('client_dashboard', tab=f'comm_{new_comm.id}'))


@app.route('/client/add', methods=['POST'])
@login_required
def add_product():
  if current_user.is_admin:
    return redirect(url_for('login'))
  barcode = request.form.get('barcode')
  name = request.form.get('name')
  quantity = int(request.form.get('quantity'))
  price = float(request.form.get('price'))
  inventory_type = request.form.get('inventory_type', 'Principal')

  new_product = Product(
      barcode=barcode,
      name=name,
      quantity=quantity,
      price=price,
      inventory_type=inventory_type,
      user_id=current_user.id,
  )
  db.session.add(new_product)
  db.session.commit()
  return redirect(url_for('client_dashboard', tab=inventory_type))


@app.route('/client/import/excel', methods=['POST'])
@login_required
def import_excel():
  if current_user.is_admin:
    return redirect(url_for('login'))

  file = request.files.get('file')
  inventory_type = request.form.get('inventory_type', 'Principal')

  if not file or file.filename == '':
    flash('Veuillez sélectionner un fichier Excel valide.')
    return redirect(url_for('client_dashboard', tab=inventory_type))

  try:
    df = pd.read_excel(file)
    for _, row in df.iterrows():
      new_prod = Product(
          barcode=str(row.get('Code-Barres', 'REF')),
          name=str(row.get('Produit', 'Article')),
          quantity=int(row.get('Quantité', 0)),
          price=float(row.get('Prix Unitaire', 0.0)),
          inventory_type=inventory_type,
          user_id=current_user.id,
      )
      db.session.add(new_prod)
    db.session.commit()
    flash('Stock importé avec succès depuis Excel !')
  except Exception as e:
    flash('Erreur lors de l’importation du fichier Excel.')

  return redirect(url_for('client_dashboard', tab=inventory_type))


@app.route('/client/export/excel/<inv_type>')
@login_required
def export_excel(inv_type):
  products = Product.query.filter_by(
      user_id=current_user.id, inventory_type=inv_type
  ).all()
  currency = current_user.currency if current_user.currency else 'DH'
  data = [{
      'Code-Barres': p.barcode,
      'Produit': p.name,
      'Quantité': p.quantity,
      f'Prix Unitaire ({currency})': p.price,
      f'Valeur Totale ({currency})': p.quantity * p.price,
  } for p in products]
  df = pd.DataFrame(data)
  output = io.BytesIO()
  with pd.ExcelWriter(output, engine='openpyxl') as writer:
    df.to_excel(writer, index=False, sheet_name=f'Inventaire_{inv_type}')
  output.seek(0)
  return send_file(
      output,
      download_name=f'inventaire_{inv_type}_stocksheet.xlsx',
      as_attachment=True,
      mimetype=(
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
      ),
  )


@app.route('/client/export/pdf/<inv_type>')
@login_required
def export_pdf(inv_type):
  products = Product.query.filter_by(
      user_id=current_user.id, inventory_type=inv_type
  ).all()
  currency = current_user.currency if current_user.currency else 'DH'

  title_label = inv_type
  if inv_type.startswith('comm_'):
    comm = CommercialInventory.query.get(int(inv_type.split('_')[1]))
    if comm:
      title_label = f'Commercial : {comm.name} ({comm.zone})'

  output = io.BytesIO()
  p = canvas.Canvas(output, pagesize=A4)
  width, height = A4

  p.setFillColorRGB(0.145, 0.388, 0.922)
  p.rect(0, height - 55, width, 55, stroke=0, fill=1)

  p.setFillColorRGB(1, 1, 1)
  p.setFont('Helvetica-Bold', 16)
  company_title = (
      current_user.company_name
      if current_user.company_name
      else current_user.username
  )
  p.drawString(40, height - 33, company_title)

  p.setFont('Helvetica', 9)
  p.drawRightString(
      width - 40,
      height - 25,
      f"ICE: {current_user.ice or '-'} | IF: {current_user.if_tax or '-'}"
      f" | RC: {current_user.rc or '-'}",
  )
  p.drawRightString(
      width - 40,
      height - 40,
      f"Tél: {current_user.phone or '-'} | Email: {current_user.email or '-'}",
  )

  p.setFillColorRGB(0, 0, 0)
  p.setFont('Helvetica-Bold', 13)
  p.drawString(40, height - 80, f'Inventaire : {title_label}')

  p.setFont('Helvetica', 8)
  p.setFillColorRGB(0.3, 0.3, 0.3)
  p.drawString(
      40,
      height - 95,
      f"Date d'édition : {datetime.now().strftime('%d/%m/%Y à %H:%M')}",
  )
  if current_user.address:
    p.drawString(40, height - 107, f'Adresse : {current_user.address}')

  p.setStrokeColorRGB(0.8, 0.8, 0.8)
  p.setLineWidth(1)
  p.line(40, height - 117, width - 40, height - 117)

  y = height - 145
  p.setFillColorRGB(0.95, 0.96, 0.98)
  p.rect(40, y - 4, width - 80, 18, stroke=0, fill=1)

  p.setFillColorRGB(0.1, 0.1, 0.1)
  p.setFont('Helvetica-Bold', 9)
  p.drawString(50, y, 'Code-Barres / Réf')
  p.drawString(180, y, 'Désignation du Produit')
  p.drawString(350, y, 'Quantité')
  p.drawString(420, y, f'P.U. ({currency})')
  p.drawString(480, y, f'Total ({currency})')
  y -= 25

  p.setFont('Helvetica', 9)
  total_general = 0
  for prod in products:
    if y < 100:
      p.showPage()
      y = height - 50
    total_ligne = prod.quantity * prod.price
    total_general += total_ligne

    p.drawString(50, y, str(prod.barcode))
    p.drawString(180, y, str(prod.name))
    p.drawString(350, y, str(prod.quantity))
    p.drawString(420, y, f'{prod.price:.2f}')
    p.drawString(480, y, f'{total_ligne:.2f}')

    p.setStrokeColorRGB(0.9, 0.9, 0.9)
    p.line(40, y - 5, width - 40, y - 5)
    y -= 20

  y -= 10
  p.setStrokeColorRGB(0.2, 0.2, 0.2)
  p.line(330, y, width - 40, y)
  y -= 18

  p.setFont('Helvetica-Bold', 11)
  p.drawString(330, y, 'TOTAL GÉNÉRAL :')
  p.drawString(460, y, f'{total_general:.2f} {currency}')

  p.setFont('Helvetica-Oblique', 7)
  p.setFillColorRGB(0.5, 0.5, 0.5)
  disclaimer_text_1 = "Clause de non-responsabilité : StockSheet.fr met à disposition l'outil de gestion d'inventaire mais ne peut"
  disclaimer_text_2 = "en aucun cas être tenu responsable des erreurs de saisie, des écarts physiques, ou des pertes/fuites de données."
  disclaimer_text_3 = "L'utilisateur / l'entreprise reste seul(e) responsable de la vérification et de l'exactitude de ses données de stock."

  p.drawCentredString(width / 2.0, 35, disclaimer_text_1)
  p.drawCentredString(width / 2.0, 25, disclaimer_text_2)
  p.drawCentredString(width / 2.0, 15, disclaimer_text_3)

  p.save()
  output.seek(0)
  return send_file(
      output,
      download_name=f'inventaire_{inv_type}_stocksheet.pdf',
      as_attachment=True,
      mimetype='application/pdf',
  )


if __name__ == '__main__':
  app.run(debug=True)
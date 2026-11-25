import secrets
import csv
import io
from datetime import date, datetime, timedelta
from flask import Response
from decimal import Decimal, InvalidOperation
from flask import Flask, render_template, request, redirect, url_for, flash, session, abort
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from config import Config
from models import db, Usuario, Producto, Categoria, Proveedor, Movimiento, Venta, DetalleVenta

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)
from fotos import fotos
app.register_blueprint(fotos)
app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Debes iniciar sesión.'

@app.context_processor
def csrf_context():
    if '_csrf_token' not in session:
        session['_csrf_token'] = secrets.token_hex(32)
    return {'csrf_token': session['_csrf_token']}

@app.before_request
def verificar_csrf():
    if request.method == 'POST':
        token = session.get('_csrf_token', '')
        if not token or not secrets.compare_digest(token, request.form.get('csrf_token', '')):
            abort(400)

@login_manager.user_loader
def cargar_usuario(id_usuario):
    usuario = db.session.get(Usuario, int(id_usuario))
    return usuario if usuario and usuario.activo else None

def exigir_admin():
    if current_user.rol != 'administrador':
        abort(403)

@app.route('/')
def inicio():
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = Usuario.query.filter_by(correo=request.form['correo'].strip().lower(), activo=True).first()
        if usuario and check_password_hash(usuario.password, request.form['password']):
            session.clear()
            login_user(usuario)
            return redirect(url_for('dashboard'))
        flash('Correo o contraseña incorrectos.')
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    lista = Producto.query.filter_by(activo=True).all()
    dias, montos = resumen_semanal()
    return render_template('dashboard.html', dias=dias, montos=montos, total_ventas=Venta.query.filter_by(estado='completada').count(), ingresos=db.session.query(db.func.coalesce(db.func.sum(Venta.total), 0)).filter_by(estado='completada').scalar(), productos=lista, total_productos=len(lista), unidades=sum(p.stock for p in lista), stock_bajo=sum(0 < p.stock <= p.stock_minimo for p in lista), agotados=sum(p.stock == 0 for p in lista))

@app.route('/productos')
@login_required
def productos():
    busqueda = request.args.get('buscar', '').strip()
    categoria = request.args.get('categoria', type=int)
    consulta = Producto.query.filter_by(activo=True)
    if busqueda:
        consulta = consulta.filter(or_(Producto.nombre.contains(busqueda), Producto.codigo.contains(busqueda)))
    if categoria:
        consulta = consulta.filter_by(id_categoria=categoria)
    return render_template('productos.html', productos=consulta.order_by(Producto.id_producto.desc()).all(), categorias=Categoria.query.order_by(Categoria.nombre).all(), busqueda=busqueda, categoria_seleccionada=categoria)

@app.route('/productos/nuevo', methods=['GET', 'POST'])
@app.route('/productos/editar/<int:id_producto>', methods=['GET', 'POST'])
@login_required
def formulario_producto(id_producto=None):
    exigir_admin()
    nuevo = id_producto is None
    producto = None if nuevo else Producto.query.filter_by(id_producto=id_producto, activo=True).first_or_404()
    if request.method == 'POST':
        try:
            codigo = request.form['codigo'].strip().upper()
            nombre = request.form['nombre'].strip()
            descripcion = request.form.get('descripcion', '').strip()
            id_categoria = int(request.form['categoria'])
            id_proveedor = int(request.form['proveedor']) if request.form.get('proveedor') else None
            compra = Decimal(request.form['precio_compra'])
            venta = Decimal(request.form['precio_venta'])
            minimo = int(request.form['stock_minimo'])
            if not codigo or not nombre or len(codigo) > 50 or len(nombre) > 150:
                raise ValueError('Código o nombre no válido.')
            for precio in (compra, venta):
                if not precio.is_finite() or not 0 <= precio <= Decimal('99999999.99') or precio != precio.quantize(Decimal('0.01')):
                    raise ValueError('Precio no válido. Usa hasta dos decimales.')
            if not 0 <= minimo <= 2147483647:
                raise ValueError('Stock mínimo no válido.')
            if not db.session.get(Categoria, id_categoria):
                raise ValueError('Categoría no válida.')
            if id_proveedor is not None and not db.session.get(Proveedor, id_proveedor):
                raise ValueError('Proveedor no válido.')
            existente = Producto.query.filter_by(codigo=codigo).first()
            if existente and existente.id_producto != id_producto:
                raise ValueError('El código del producto ya existe.')
            if nuevo:
                producto = Producto(stock=0, activo=True)
            producto.codigo = codigo
            producto.nombre = nombre
            producto.descripcion = descripcion
            producto.id_categoria = id_categoria
            producto.id_proveedor = id_proveedor
            producto.precio_compra = compra
            producto.precio_venta = venta
            producto.stock_minimo = minimo
            db.session.add(producto)
            db.session.commit()
            flash('Producto registrado correctamente.' if nuevo else 'Producto actualizado correctamente.', 'success')
            return redirect(url_for('productos'))
        except (ValueError, InvalidOperation) as error:
            db.session.rollback()
            flash(str(error) or 'Datos no válidos.', 'error')
        except IntegrityError:
            db.session.rollback()
            flash('Código duplicado o referencia no válida.', 'error')
        if nuevo:
            producto = None
    return render_template('formulario_producto.html', producto=producto, categorias=Categoria.query.all(), proveedores=Proveedor.query.all())

@app.route('/productos/desactivar/<int:id_producto>', methods=['POST'])
@login_required
def desactivar_producto(id_producto):
    exigir_admin()
    producto = Producto.query.filter_by(id_producto=id_producto, activo=True).with_for_update().first_or_404()
    if producto.stock > 0:
        db.session.rollback()
        flash('No puedes desactivar un producto con existencias.', 'error')
    else:
        producto.activo = False
        db.session.commit()
        flash('Producto desactivado correctamente.', 'success')
    return redirect(url_for('productos'))

# Catálogos de categorías y proveedores
CATALOGOS = {
    'categorias': (Categoria, 'id_categoria', 'Categorías', [('nombre', 'Nombre', 100), ('descripcion', 'Descripción', 255)]),
    'proveedores': (Proveedor, 'id_proveedor', 'Proveedores', [('nombre', 'Nombre', 150), ('telefono', 'Teléfono', 20), ('correo', 'Correo', 150), ('direccion', 'Dirección', 255)])
}

def obtener_catalogo(tipo):
    if tipo not in CATALOGOS:
        abort(404)
    return CATALOGOS[tipo]

@app.route('/catalogos/<tipo>')
@login_required
def catalogo(tipo):
    modelo, pk, titulo, campos = obtener_catalogo(tipo)
    return render_template('catalogo.html', tipo=tipo, pk=pk, titulo=titulo, campos=campos, registros=modelo.query.order_by(modelo.nombre).all())

@app.route('/catalogos/<tipo>/nuevo', methods=['GET', 'POST'])
@app.route('/catalogos/<tipo>/editar/<int:id_registro>', methods=['GET', 'POST'])
@login_required
def formulario_catalogo(tipo, id_registro=None):
    exigir_admin()
    modelo, pk, titulo, campos = obtener_catalogo(tipo)
    registro = db.get_or_404(modelo, id_registro) if id_registro is not None else None
    valores = {campo: getattr(registro, campo) or '' if registro else '' for campo, _, _ in campos}
    if request.method == 'POST':
        valores = {campo: request.form.get(campo, '').strip() for campo, _, _ in campos}
        try:
            if not valores['nombre']:
                raise ValueError('El nombre es obligatorio.')
            for campo, etiqueta, limite in campos:
                if len(valores[campo]) > limite:
                    raise ValueError(f'{etiqueta}: máximo {limite} caracteres.')
            if tipo == 'categorias':
                existente = Categoria.query.filter_by(nombre=valores['nombre']).first()
                if existente and existente.id_categoria != id_registro:
                    raise ValueError('La categoría ya existe.')
            objeto = registro if registro is not None else modelo()
            for campo, valor in valores.items():
                setattr(objeto, campo, valor or None)
            db.session.add(objeto)
            db.session.commit()
            flash('Registro guardado correctamente.', 'success')
            return redirect(url_for('catalogo', tipo=tipo))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), 'error')
        except IntegrityError:
            db.session.rollback()
            flash('No se pudo guardar: registro duplicado o datos en conflicto.', 'error')
    return render_template('formulario_catalogo.html', tipo=tipo, titulo=titulo, campos=campos, valores=valores, editando=id_registro is not None)

@app.route('/catalogos/<tipo>/eliminar/<int:id_registro>', methods=['POST'])
@login_required
def eliminar_catalogo(tipo, id_registro):
    exigir_admin()
    modelo, pk, _, _ = obtener_catalogo(tipo)
    registro = db.get_or_404(modelo, id_registro)
    if Producto.query.filter(getattr(Producto, pk) == id_registro).first():
        flash('No puedes eliminar un registro asociado a productos.', 'error')
    else:
        try:
            db.session.delete(registro)
            db.session.commit()
            flash('Registro eliminado correctamente.', 'success')
        except IntegrityError:
            db.session.rollback()
            flash('No se puede eliminar: existen registros relacionados.', 'error')
    return redirect(url_for('catalogo', tipo=tipo))

# Inventario: actualización y movimiento en una sola transacción
@app.route('/inventario', methods=['GET', 'POST'])
@login_required
def inventario():
    if request.method == 'POST':
        exigir_admin()
        try:
            id_producto = int(request.form['id_producto'])
            tipo = request.form['tipo']
            cantidad = int(request.form['cantidad'])
            motivo = request.form.get('motivo', '').strip()
            if tipo not in ('entrada', 'salida') or not 0 < cantidad <= 2147483647 or not motivo or len(motivo) > 255:
                raise ValueError('Indica un tipo, cantidad positiva y motivo válido.')
            producto = Producto.query.filter_by(id_producto=id_producto, activo=True).with_for_update().populate_existing().first()
            if producto is None:
                raise ValueError('Producto no disponible.')
            anterior = producto.stock
            nuevo = anterior + cantidad if tipo == 'entrada' else anterior - cantidad
            if nuevo < 0:
                raise ValueError('Existencias insuficientes para realizar la salida.')
            if nuevo > 2147483647:
                raise ValueError('Se excede el límite de existencias.')
            producto.stock = nuevo
            db.session.add(Movimiento(id_producto=id_producto, id_usuario=current_user.id_usuario, tipo=tipo, cantidad=cantidad, stock_anterior=anterior, stock_nuevo=nuevo, motivo=motivo))
            db.session.commit()
            flash('Movimiento registrado correctamente.', 'success')
        except ValueError as error:
            db.session.rollback()
            flash(str(error), 'error')
        return redirect(url_for('inventario'))
    lista = Producto.query.filter_by(activo=True).order_by(Producto.nombre).all()
    historial = Movimiento.query.options(db.joinedload(Movimiento.producto), db.joinedload(Movimiento.usuario)).order_by(Movimiento.id_movimiento.desc()).limit(100).all()
    return render_template('inventario.html', productos=lista, historial=historial)


# Ventas: bloqueo ordenado de productos y transacción atómica
@app.route('/ventas', methods=['GET', 'POST'])
@login_required
def ventas():
    if request.method == 'POST':
        try:
            ids = request.form.getlist('id_producto')
            cantidades = request.form.getlist('cantidad')
            if not ids or len(ids) != len(cantidades) or len(ids) > 50:
                raise ValueError('Agrega entre 1 y 50 líneas de venta.')
            carrito = {}
            for identificador, cantidad in zip(ids, cantidades):
                i, n = int(identificador), int(cantidad)
                if i <= 0 or not 0 < n <= 2147483647:
                    raise ValueError('Cantidad o producto inválido.')
                carrito[i] = carrito.get(i, 0) + n
            productos = {}
            total = Decimal('0.00')
            for i in sorted(carrito):
                p = Producto.query.filter_by(id_producto=i, activo=True).with_for_update().populate_existing().first()
                if not p or p.stock < carrito[i]:
                    raise ValueError('Existencias insuficientes o producto no disponible: ' + (p.nombre if p else str(i)))
                productos[i] = p
                total += p.precio_venta * carrito[i]
            if total > Decimal('9999999999.99'):
                raise ValueError('El total excede el límite permitido.')
            venta = Venta(id_usuario=current_user.id_usuario, total=total, estado='completada')
            db.session.add(venta)
            db.session.flush()
            for i, p in productos.items():
                n = carrito[i]
                anterior = p.stock
                p.stock -= n
                db.session.add(DetalleVenta(id_venta=venta.id_venta, id_producto=i, cantidad=n, precio_unitario=p.precio_venta, subtotal=p.precio_venta*n))
                db.session.add(Movimiento(id_producto=i, id_usuario=current_user.id_usuario, tipo='salida', cantidad=n, stock_anterior=anterior, stock_nuevo=p.stock, motivo=f'Venta #{venta.id_venta}'))
            identificador = venta.id_venta
            db.session.commit()
            flash('Venta registrada correctamente.', 'success')
            return redirect(url_for('detalle_venta', id_venta=identificador))
        except ValueError as error:
            db.session.rollback()
            flash(str(error), 'error')
            return redirect(url_for('ventas'))
    return render_template('ventas.html', productos=Producto.query.filter(Producto.activo == True, Producto.stock > 0).order_by(Producto.nombre).all(), ventas=Venta.query.order_by(Venta.id_venta.desc()).limit(100).all())

@app.route('/ventas/<int:id_venta>')
@login_required
def detalle_venta(id_venta):
    return render_template('detalle_venta.html', venta=db.get_or_404(Venta, id_venta))

def resumen_semanal():
    hoy = date.today()
    dias = [hoy - timedelta(days=i) for i in range(6, -1, -1)]
    filas = db.session.query(db.func.date(Venta.fecha), db.func.sum(Venta.total)).filter(Venta.estado == 'completada', Venta.fecha >= dias[0], Venta.fecha < hoy + timedelta(days=1)).group_by(db.func.date(Venta.fecha)).all()
    valores = {str(d): float(v) for d, v in filas}
    return [d.strftime('%d/%m') for d in dias], [valores.get(str(d), 0) for d in dias]

def consulta_reporte():
    try:
        desde = date.fromisoformat(request.args.get('desde') or date.today().replace(day=1).isoformat())
        hasta = date.fromisoformat(request.args.get('hasta') or date.today().isoformat())
        if desde > hasta or hasta == date.max:
            raise ValueError()
    except ValueError:
        abort(400, 'Rango de fechas inválido.')
    filas = Venta.query.filter(Venta.fecha >= desde, Venta.fecha < hasta + timedelta(days=1), Venta.estado == 'completada').order_by(Venta.fecha.desc()).all()
    return desde, hasta, filas

@app.route('/reportes')
@login_required
def reportes():
    exigir_admin()
    desde, hasta, filas = consulta_reporte()
    return render_template('reportes.html', desde=desde, hasta=hasta, ventas=filas, ingresos=sum((v.total for v in filas), Decimal('0')), unidades=sum(d.cantidad for v in filas for d in v.detalles))

def csv_seguro(valor):
    if isinstance(valor, str) and valor.lstrip().startswith(('=', '+', '-', '@')):
        return "'" + valor
    return valor

@app.route('/reportes/csv')
@login_required
def reporte_csv():
    exigir_admin()
    desde, hasta, filas = consulta_reporte()
    archivo = io.StringIO()
    escritor = csv.writer(archivo)
    escritor.writerow(['Venta', 'Fecha', 'Usuario', 'Producto', 'Cantidad', 'Precio unitario', 'Subtotal'])
    for v in filas:
        for d in v.detalles:
            escritor.writerow([csv_seguro(x) for x in [v.id_venta, v.fecha, v.usuario.nombre, d.producto.nombre, d.cantidad, d.precio_unitario, d.subtotal]])
    return Response('\ufeff' + archivo.getvalue(), mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename=ventas_cloudstock.csv'})

@app.errorhandler(SQLAlchemyError)
def error_base_datos(error):
    db.session.rollback()
    app.logger.error('Error de base de datos: %s', type(error).__name__)
    return 'CloudStock: Base de datos temporalmente no disponible. Intenta nuevamente más tarde.', 503

@app.errorhandler(403)
def acceso_denegado(error):
    return 'CloudStock: No tienes permisos para realizar esta operación.', 403

if __name__ == '__main__':
    app.run(debug=True)

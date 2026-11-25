from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, current_app
from flask_login import login_required, current_user
from flask import abort
from botocore.exceptions import BotoCoreError, ClientError
from models import db, Producto
from storage import storage, guardar_imagen, versiones, restaurar, StorageUnavailable, MAX_BYTES

fotos = Blueprint('fotos', __name__)
ERRORES_S3 = (BotoCoreError, ClientError, StorageUnavailable)

@fotos.get('/productos/<int:id_producto>/imagen')
@login_required
def imagen(id_producto):
    p = db.get_or_404(Producto, id_producto)
    if p.imagen_s3:
        try:
            client, bucket = storage()
            obj = client.get_object(Bucket=bucket, Key=p.imagen_s3)
            try:
                data = obj['Body'].read(MAX_BYTES + 1)
            finally:
                obj['Body'].close()
            if len(data) <= MAX_BYTES and obj.get('ContentType') == 'image/jpeg':
                return Response(data, mimetype='image/jpeg', headers={'Cache-Control':'private, no-store', 'X-Content-Type-Options':'nosniff'})
        except ERRORES_S3 as exc:
            current_app.logger.warning('S3 no disponible: %s', type(exc).__name__)
    return Response('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="90"><rect width="120" height="90" rx="8" fill="#334155"/><text x="60" y="48" text-anchor="middle" font-size="12" fill="#cbd5e1">Sin imagen</text></svg>', mimetype='image/svg+xml', headers={'Cache-Control':'no-store'})

@fotos.route('/productos/<int:id_producto>/fotografias', methods=['GET','POST'])
@login_required
def gestionar(id_producto):
    if current_user.rol != 'administrador':
        abort(403)
    p = Producto.query.filter_by(id_producto=id_producto, activo=True).first_or_404()
    if request.method == 'POST':
        try:
            if request.form.get('accion') == 'restaurar':
                version = request.form.get('version','')
                if not p.imagen_s3 or version not in {v['VersionId'] for v in versiones(p.imagen_s3)}:
                    raise ValueError('Versión no válida.')
                restaurar(p.imagen_s3, version)
                flash('Versión recuperada correctamente.', 'success')
            else:
                archivo = request.files.get('foto')
                if not archivo:
                    raise ValueError('Selecciona una fotografía.')
                p.imagen_s3 = guardar_imagen(archivo, p.imagen_s3)
                db.session.commit()
                flash('Fotografía guardada en Amazon S3.', 'success')
        except ValueError as exc:
            db.session.rollback()
            flash(str(exc), 'error')
        except ERRORES_S3 as exc:
            db.session.rollback()
            current_app.logger.warning('Error S3: %s', type(exc).__name__)
            flash('Amazon S3 no disponible. El inventario continúa funcionando.', 'error')
        return redirect(url_for('fotos.gestionar', id_producto=id_producto))
    historial = []
    aviso = False
    if p.imagen_s3:
        try:
            historial = versiones(p.imagen_s3)
        except ERRORES_S3:
            aviso = True
    return render_template('fotografias.html', producto=p, historial=historial, aviso=aviso)

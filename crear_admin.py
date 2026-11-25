from getpass import getpass
from werkzeug.security import generate_password_hash

from app import app
from models import db, Usuario


with app.app_context():

    correo = "admin@cloudstock.com"

    existente = Usuario.query.filter_by(
        correo=correo
    ).first()

    if existente:

        print("El administrador ya existe.")

    else:

        password = getpass("Contraseña del administrador: ")
        confirmar = getpass("Confirma la contraseña: ")

        if password != confirmar or len(password) < 8:
            raise SystemExit(
                "Las contraseñas no coinciden o son demasiado cortas."
            )

        admin = Usuario(
            nombre="Administrador",
            correo=correo,
            password=generate_password_hash(password),
            rol="administrador",
            activo=True
        )

        db.session.add(admin)
        db.session.commit()

        print("Administrador creado correctamente.")
        print("Correo:", correo)
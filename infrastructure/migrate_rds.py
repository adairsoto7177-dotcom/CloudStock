"""Copy all seven CloudStock tables from local MariaDB to an empty RDS database."""
from pathlib import Path
import pymysql
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
TABLES = ('usuarios','categorias','proveedores','productos','ventas','detalle_ventas','movimientos')


def connect(cfg, remote=False):
    kwargs = dict(host=cfg['DB_HOST'], port=int(cfg.get('DB_PORT',3306)), user=cfg['DB_USER'], password=cfg.get('DB_PASSWORD') or '', database=cfg['DB_NAME'], charset='utf8mb4', connect_timeout=10, autocommit=False)
    if remote:
        kwargs.update(ssl_ca=cfg['DB_SSL_CA'], ssl_verify_cert=True, ssl_verify_identity=True)
    return pymysql.connect(**kwargs)


def main():
    local = dotenv_values(ROOT / '.env')
    remote = dotenv_values(ROOT / '.env.rds')
    if local.get('DB_HOST') not in ('localhost','127.0.0.1','::1'):
        raise SystemExit('El archivo .env debe apuntar a la base local durante la migracion.')
    if remote.get('DB_HOST') == local.get('DB_HOST'):
        raise SystemExit('Origen y destino deben ser distintos.')
    with connect(local) as src, connect(remote, True) as dst:
        with src.cursor() as a, dst.cursor() as b:
            # The SQL schema is known to contain simple DDL, no stored procedures.
            schema = (ROOT / 'sql' / 'schema.sql').read_text(encoding='utf-8-sig')
            schema = '\n'.join(line for line in schema.splitlines() if not line.lstrip().startswith('--'))
            for statement in schema.split(';'):
                if statement.strip():
                    b.execute(statement)
            for table in TABLES:
                b.execute(f'SELECT COUNT(*) FROM `{table}`')
                if b.fetchone()[0]:
                    raise SystemExit(f'Destino no vacio ({table}). No se copiaron registros.')
            a.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
            a.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT')
            try:
                for table in TABLES:
                    a.execute(f'SELECT * FROM `{table}`')
                    columns = [d[0] for d in a.description]
                    rows = a.fetchall()
                    names = ','.join(f'`{c}`' for c in columns)
                    marks = ','.join(['%s']*len(columns))
                    if rows:
                        b.executemany(f'INSERT INTO `{table}` ({names}) VALUES ({marks})', rows)
                    b.execute(f'SELECT COUNT(*) FROM `{table}`')
                    count = b.fetchone()[0]
                    if count != len(rows):
                        raise RuntimeError(f'Conteo diferente en {table}')
                    print(f'{table}: local={len(rows)} RDS={count}')
                dst.commit()
                print('Migracion completada. Datos originales conservados.')
            except Exception:
                dst.rollback()
                raise
            finally:
                src.rollback()

if __name__ == '__main__':
    main()

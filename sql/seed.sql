-- CloudStock
-- Registros iniciales de prueba

USE cloudstock;

-- Categorías

INSERT INTO categorias (nombre, descripcion)
VALUES
('Procesadores', 'Procesadores AMD e Intel'),
('Tarjetas graficas', 'Tarjetas de video'),
('Almacenamiento', 'Discos SSD y HDD'),
('Memorias RAM', 'Memorias para computadoras'),
('Perifericos', 'Teclados, mouse y accesorios'),
('Monitores', 'Pantallas para computadoras');

-- Proveedores

INSERT INTO proveedores (nombre, telefono, correo)
VALUES
('Tech Distribution', '3300000001', 'ventas@tech.example'),
('PC Solutions', '3300000002', 'ventas@pc.example'),
('Digital Hardware', '3300000003', 'ventas@digital.example');

-- Productos

INSERT INTO productos
(codigo, nombre, id_categoria, id_proveedor,
 precio_compra, precio_venta, stock, stock_minimo)
VALUES
('CPU001', 'AMD Ryzen 5 5500', 1, 1, 1200, 1599, 15, 5),
('GPU001', 'AMD RX 6700', 2, 1, 4000, 4999, 8, 3),
('SSD001', 'SSD M.2 1TB', 3, 2, 800, 1299, 20, 5),
('RAM001', 'RAM DDR4 16GB', 4, 2, 450, 799, 12, 5),
('PER001', 'Teclado mecanico', 5, 3, 500, 850, 17, 5),
('PER002', 'Mouse Logitech', 5, 3, 250, 450, 25, 5),
('MON001', 'Monitor 24 pulgadas', 6, 3, 1800, 2499, 3, 5),
('SSD002', 'SSD SATA 480GB', 3, 2, 350, 599, 0, 5);
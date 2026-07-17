CREATE TABLE pacientes(
    telefono VARCHAR(20) PRIMARY KEY,
    nombre VARCHAR(100),
    dni VARCHAR(20),
    obra_social VARCHAR(100) NULL,
    fecha_registro TIMESTAMP DEFAULT NOW()
);

CREATE TABLE turnos(
    idTurno SERIAL PRIMARY KEY,
    codigo_turno VARCHAR(10) UNIQUE,
    telefono_paciente VARCHAR(20) REFERENCES pacientes(telefono),
    fecha DATE,
    hora TIME,
    estado VARCHAR(20),
    recordatorio_enviado BOOLEAN DEFAULT false
);

CREATE TABLE preguntas_frecuentes(
    idPregunta SERIAL PRIMARY KEY,
    categoria VARCHAR(50),
    pregunta TEXT,
    respuesta TEXT
);
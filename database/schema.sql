CREATE TABLE pacientes(
    dni VARCHAR(20) PRIMARY KEY,
    telefono VARCHAR(20),
    nombre VARCHAR(100),
    obra_social VARCHAR(100) NULL,
    fecha_registro TIMESTAMP DEFAULT NOW()
);

CREATE TABLE turnos(
    idTurno SERIAL PRIMARY KEY,
    codigo_turno VARCHAR(10) UNIQUE,
    dni_paciente VARCHAR(20) REFERENCES pacientes(dni),
    fecha DATE,
    hora TIME,
    estado VARCHAR(20) DEFAULT 'agendado',
    recordatorio_enviado BOOLEAN DEFAULT false
);

-- Evita que dos turnos queden agendados en el mismo dia+hora (race condition
-- entre el momento en que se ofrece un horario libre y el momento en que se
-- confirma la reserva).
CREATE UNIQUE INDEX turnos_slot_agendado_idx ON turnos(fecha, hora) WHERE estado = 'agendado';

CREATE TABLE preguntas_frecuentes(
    idPregunta SERIAL PRIMARY KEY,
    categoria VARCHAR(50),
    pregunta TEXT,
    respuesta TEXT
);
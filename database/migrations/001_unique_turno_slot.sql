-- Migracion para bases de datos ya existentes (creadas antes de este fix).
-- Evita que dos turnos queden agendados en el mismo dia+hora.
--
-- IMPORTANTE: correr esto a mano contra la base real antes de desplegar el
-- fix de src/postgres.py que depende de esta restriccion. Si ya existen
-- turnos duplicados (mismo fecha+hora, ambos 'agendado'), este CREATE INDEX
-- va a fallar -- en ese caso hay que resolver el duplicado a mano primero.

CREATE UNIQUE INDEX IF NOT EXISTS turnos_slot_agendado_idx
    ON turnos(fecha, hora)
    WHERE estado = 'agendado';

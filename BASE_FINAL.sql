-- =====================================================================
--  BASE_FINAL.sql — Sistema de Control de Carga de Motos
--
--  Uso: Supabase > SQL Editor > New query > pegar TODO > Run.
--  Crea la base completa. Se puede ejecutar varias veces y no borra
--  usuarios, cargas ni lecturas.
--
--  Modelo:
--    usuarios ──< sesiones                 login, una sesión activa por usuario
--    super_admin                           clave para registrar administradores
--    camaras                               cámaras del muelle (USB, IP o video)
--    cargas   ──< motos_carga              archivo REFRENCIAS MOTOS AKT de cada camión
--    cargas   ──< lecturas_qr              cada QR que leyó la cámara
--    cargas   ──< detecciones_yolo         cada moto que YOLO siguió (tracking)
--    cargas   ──< alertas                  avisos: faltantes, sobrantes, ajenas, sin identificar
--
--  Datos sensibles (los protege el backend con la librería cryptography):
--    hash:    contraseñas (scrypt) y token de sesión (SHA-256)
--    cifrado: correo, IP y navegador de la sesión, conductor, fuente de la cámara
--    huella:  email_hash (HMAC) para evitar correos duplicados sin guardarlos en claro
-- =====================================================================


-- =====================================================================
-- TABLAS
-- =====================================================================
create table if not exists usuarios (
  id             bigint generated always as identity primary key,
  nombre         text        not null,
  usuario        text        not null,                 -- nombre de inicio de sesión (minúsculas)
  email          text,                                 -- CIFRADO
  email_hash     text,                                 -- huella HMAC del correo
  password_hash  text        not null,                 -- hash scrypt
  rol            text        not null default 'empleado' check (rol in ('admin', 'empleado')),
  activo         boolean     not null default true,
  creado_en      timestamptz not null default now(),
  ultimo_acceso  timestamptz
);

create table if not exists super_admin (
  id             bigint generated always as identity primary key,
  usuario        text        not null unique,
  password_hash  text        not null,                 -- hash scrypt de la clave
  creado_en      timestamptz not null default now()
);

create table if not exists sesiones (
  id                bigint generated always as identity primary key,
  usuario_id        bigint      not null references usuarios (id) on delete cascade,
  token_hash        text        not null unique,       -- SHA-256 del token de la cookie
  ip                text,                              -- CIFRADO
  user_agent        text,                              -- CIFRADO
  creada_en         timestamptz not null default now(),
  ultima_actividad  timestamptz not null default now(),  -- la renueva el "latido" del navegador
  activa            boolean     not null default true,
  cerrada_en        timestamptz,
  motivo_cierre     text        check (motivo_cierre in ('LOGOUT', 'EXPIRADA', 'CERRADA_POR_ADMIN', 'USUARIO_DESACTIVADO'))
);

create table if not exists camaras (
  id          bigint generated always as identity primary key,
  nombre      text        not null unique,
  fuente      text        not null,   -- CIFRADO: "0" (USB) | rtsp://usuario:clave@ip/... | ruta a un video
  ubicacion   text,
  activa      boolean     not null default true,
  creada_en   timestamptz not null default now()
);

create table if not exists cargas (
  id               bigint generated always as identity primary key,
  codigo_contrato  text        not null,               -- ej. CARGA-20260930-01
  fecha            date        not null default ((now() at time zone 'America/Bogota')::date),
  destino          text,
  placa_camion     text,
  conductor        text,                               -- CIFRADO
  estado           text        not null default 'PENDIENTE'
                               check (estado in ('PENDIENTE', 'EN_CARGA', 'PAUSADA', 'COMPLETA', 'INCOMPLETA', 'CANCELADA')),
  camara_id        bigint      references camaras (id) on delete set null,
  archivo_origen   text,                               -- REFRENCIAS MOTOS AKT.xlsx
  creada_por       bigint      references usuarios (id) on delete set null,
  creada_en        timestamptz not null default now(),
  iniciada_en      timestamptz,
  finalizada_en    timestamptz,
  finalizada_por   bigint      references usuarios (id) on delete set null,
  unique (codigo_contrato, fecha)
);

-- Una fila del Excel = una moto (Artículo | Marca | Descripción | COD INT).
-- Si un artículo se repite, son varias unidades de esa referencia.
create table if not exists motos_carga (
  id           bigint generated always as identity primary key,
  carga_id     bigint      not null references cargas (id) on delete cascade,
  articulo     text        not null,               -- código de 13 dígitos
  marca        text,
  descripcion  text,                               -- ej. Moto AK125TTR CBS G/N/V 26 PT
  referencia   text,                               -- COD INT, ej. AK125TTR EIII
  estado       text        not null default 'PENDIENTE' check (estado in ('PENDIENTE', 'CARGADA')),
  qr_leido     text,                               -- QR con el que se cargó (detecta el QR ya usado)
  track_id     text,                               -- seguimiento YOLO que la confirmó visualmente
  cargada_en   timestamptz
);

create table if not exists lecturas_qr (
  id             bigint generated always as identity primary key,
  carga_id       bigint      not null references cargas (id) on delete cascade,
  camara_id      bigint      references camaras (id) on delete set null,
  moto_carga_id  bigint      references motos_carga (id) on delete set null,
  contenido      text        not null,             -- texto leído del QR
  resultado      text        not null
                             check (resultado in ('VALIDA', 'DUPLICADA', 'SOBRANTE', 'NO_PERTENECE', 'OTRA_CARGA')),
  track_id       text,                             -- moto de YOLO que llevaba el QR
  evidencia      text,                             -- foto guardada en el servidor
  leida_en       timestamptz not null default now()
);

create table if not exists detecciones_yolo (
  id             bigint generated always as identity primary key,
  carga_id       bigint      not null references cargas (id) on delete cascade,
  camara_id      bigint      references camaras (id) on delete set null,
  track_id       text        not null,             -- ej. C1-101530-T12
  confianza      numeric(4, 3),
  fotogramas     int         not null default 0,
  primera_vez    timestamptz not null,
  ultima_vez     timestamptz not null,
  qr_contenido   text,                             -- QR asociado a esa moto
  moto_carga_id  bigint      references motos_carga (id) on delete set null,
  estado         text        not null check (estado in ('IDENTIFICADA', 'SIN_IDENTIFICAR')),
  evidencia      text,
  creada_en      timestamptz not null default now(),
  unique (carga_id, track_id)
);

create table if not exists alertas (
  id             bigint generated always as identity primary key,
  carga_id       bigint      references cargas (id) on delete cascade,
  tipo           text        not null check (tipo in ('MOTOS_FALTANTES', 'MOTO_SOBRANTE', 'MOTO_OTRA_CARGA',
                                                      'QR_NO_PERTENECE', 'MOTO_SIN_IDENTIFICAR')),
  severidad      text        not null default 'ALTA' check (severidad in ('BAJA', 'MEDIA', 'ALTA', 'CRITICA')),
  titulo         text        not null,
  mensaje        text        not null,
  detalle        jsonb,                            -- ej. lista de motos faltantes
  leida          boolean     not null default false,
  leida_por      bigint      references usuarios (id) on delete set null,
  leida_en       timestamptz,
  email_enviado  boolean     not null default false,
  creada_en      timestamptz not null default now()
);


-- =====================================================================
-- LIMPIEZA DE VERSIONES ANTERIORES
-- Deja una base ya existente igual a las tablas de arriba (quita lo que el
-- sistema no usa). En una base nueva no cambia nada.
-- =====================================================================
do $$
declare
  f record;
begin
  -- Las funciones se vuelven a crear abajo, así nunca quedan versiones viejas
  for f in select p.oid::regprocedure as firma
             from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and (p.proname like 'app\_%' or p.proname like 'akt\_%') loop
    execute format('drop function %s cascade', f.firma);
  end loop;
end $$;

drop view if exists v_lecturas, v_camaras, v_usuarios_admin, v_alertas, v_cargas, v_resumen_cargas cascade;

alter table cargas      drop column if exists observaciones;
alter table motos_carga drop column if exists chasis,
                        drop column if exists motor,
                        drop column if exists color,
                        drop column if exists identificada_por,
                        drop column if exists cargada_por;
alter table motos_carga alter column articulo set not null;
alter table lecturas_qr drop column if exists origen,
                        drop column if exists usuario_id;

alter table alertas drop constraint if exists alertas_tipo_check;
alter table alertas add constraint alertas_tipo_check
  check (tipo in ('MOTOS_FALTANTES', 'MOTO_SOBRANTE', 'MOTO_OTRA_CARGA', 'QR_NO_PERTENECE', 'MOTO_SIN_IDENTIFICAR'));


-- =====================================================================
-- ÍNDICES
-- =====================================================================
create unique index if not exists usuarios_usuario_uq             on usuarios (lower(usuario));
create unique index if not exists usuarios_email_hash_uq          on usuarios (email_hash) where email_hash is not null;
create unique index if not exists sesiones_una_activa_por_usuario on sesiones (usuario_id) where activa;  -- sesión única
create index        if not exists sesiones_usuario_idx            on sesiones (usuario_id, creada_en desc);
create index        if not exists cargas_fecha_idx                on cargas (fecha desc);
create index        if not exists cargas_estado_idx               on cargas (estado);
create index        if not exists motos_carga_articulo_idx        on motos_carga (carga_id, articulo);
create index        if not exists motos_carga_estado_idx          on motos_carga (carga_id, estado);
create index        if not exists motos_carga_qr_idx              on motos_carga (carga_id, qr_leido);
create index        if not exists lecturas_qr_carga_idx           on lecturas_qr (carga_id, leida_en desc);
create index        if not exists lecturas_qr_track_idx           on lecturas_qr (carga_id, track_id);
create index        if not exists detecciones_yolo_carga_idx      on detecciones_yolo (carga_id, creada_en desc);
create index        if not exists alertas_pendientes_idx          on alertas (leida, creada_en desc);


-- =====================================================================
-- VISTAS (nunca exponen password_hash ni email_hash)
-- =====================================================================
create view v_resumen_cargas with (security_invoker = true) as
select c.*,
       count(m.id)                                       as total_motos,
       count(m.id) filter (where m.estado = 'CARGADA')   as motos_cargadas,
       count(m.id) filter (where m.estado = 'PENDIENTE') as motos_faltantes
  from cargas c
  left join motos_carga m on m.carga_id = c.id
 group by c.id;

create view v_cargas with (security_invoker = true) as
select r.*,
       k.nombre as camara_nombre, k.fuente as camara_fuente, k.activa as camara_activa,
       u.nombre as creada_por_nombre, f.nombre as finalizada_por_nombre
  from v_resumen_cargas r
  left join camaras  k on k.id = r.camara_id
  left join usuarios u on u.id = r.creada_por
  left join usuarios f on f.id = r.finalizada_por;

create view v_alertas with (security_invoker = true) as
select a.*, c.codigo_contrato, c.destino, c.placa_camion, c.fecha, u.nombre as leida_por_nombre
  from alertas a
  left join cargas   c on c.id = a.carga_id
  left join usuarios u on u.id = a.leida_por;

create view v_usuarios_admin with (security_invoker = true) as
select u.id, u.nombre, u.usuario, u.email, u.rol, u.activo, u.creado_en, u.ultimo_acceso,
       s.id as sesion_id, s.ip, s.creada_en as sesion_desde, s.ultima_actividad
  from usuarios u
  left join sesiones s on s.usuario_id = u.id and s.activa;

create view v_camaras with (security_invoker = true) as
select k.*, c.id as carga_id, c.codigo_contrato
  from camaras k
  left join cargas c on c.camara_id = k.id and c.estado = 'EN_CARGA';


-- =====================================================================
-- FUNCIONES (el backend las llama con la clave secreta de Supabase).
-- Todo lo que debe ser atómico ocurre aquí, en una sola transacción.
-- =====================================================================

-- Versión del esquema: la app la revisa al arrancar
create function app_esquema()
returns int language sql stable set search_path = public as $$ select 6 $$;


-- ---------------------------------------------------------------------
-- Usuarios y sesiones
-- ---------------------------------------------------------------------
create function app_registrar_usuario(
  p_nombre text, p_usuario text, p_email text, p_email_hash text, p_password_hash text, p_rol text)
returns jsonb language plpgsql set search_path = public as $$
begin
  if p_rol not in ('admin', 'empleado') then
    raise exception 'Rol inválido.';
  end if;
  insert into usuarios (nombre, usuario, email, email_hash, password_hash, rol)
  values (p_nombre, lower(p_usuario), p_email, p_email_hash, p_password_hash, p_rol);
  return jsonb_build_object('ok', true, 'rol', p_rol);
exception when unique_violation then
  return jsonb_build_object('ok', false, 'error', 'duplicado');
end $$;


-- Abre sesión solo si el usuario no tiene otra activa (en otro dispositivo)
create function app_abrir_sesion(p_usuario_id bigint, p_token_hash text, p_ip text, p_user_agent text, p_timeout int)
returns jsonb language plpgsql set search_path = public as $$
declare
  r record;
begin
  perform 1 from usuarios where id = p_usuario_id for update;  -- dos logins a la vez no pasan juntos

  update sesiones set activa = false, cerrada_en = now(), motivo_cierre = 'EXPIRADA'
   where usuario_id = p_usuario_id and activa
     and ultima_actividad < now() - make_interval(secs => p_timeout);

  select ip, creada_en into r from sesiones where usuario_id = p_usuario_id and activa;
  if r.creada_en is not null then
    return jsonb_build_object('ok', false, 'ip', r.ip, 'creada_en', r.creada_en);
  end if;

  insert into sesiones (usuario_id, token_hash, ip, user_agent) values (p_usuario_id, p_token_hash, p_ip, p_user_agent);
  update usuarios set ultimo_acceso = now() where id = p_usuario_id;
  return jsonb_build_object('ok', true);
end $$;


-- Valida la sesión en cada petición: la expira si no hubo latido o la renueva
create function app_validar_sesion(p_token_hash text, p_timeout int)
returns jsonb language plpgsql set search_path = public as $$
declare
  r record;
  v_motivo text;
begin
  select s.id, s.activa, s.motivo_cierre, u.id as uid, u.nombre, u.usuario, u.rol, u.activo,
         extract(epoch from now() - s.ultima_actividad) as inactivo
    into r
    from sesiones s join usuarios u on u.id = s.usuario_id
   where s.token_hash = p_token_hash;

  if r.id is null then
    return jsonb_build_object('estado', 'cerrada', 'motivo', null);
  end if;
  if not r.activa then
    return jsonb_build_object('estado', 'cerrada', 'motivo', r.motivo_cierre);
  end if;
  if not r.activo or r.inactivo > p_timeout then
    v_motivo := case when r.activo then 'EXPIRADA' else 'USUARIO_DESACTIVADO' end;
    update sesiones set activa = false, cerrada_en = now(), motivo_cierre = v_motivo where id = r.id;
    return jsonb_build_object('estado', 'cerrada', 'motivo', v_motivo);
  end if;

  if r.inactivo > 10 then
    update sesiones set ultima_actividad = now() where id = r.id;
  end if;
  return jsonb_build_object('estado', 'ok', 'usuario', jsonb_build_object(
    'sesion_id', r.id, 'id', r.uid, 'nombre', r.nombre, 'usuario', r.usuario, 'rol', r.rol));
end $$;


create function app_cerrar_sesion(p_sesion_id bigint, p_motivo text)
returns void language sql set search_path = public as $$
  update sesiones set activa = false, cerrada_en = now(), motivo_cierre = p_motivo
   where id = p_sesion_id and activa;
$$;


create function app_set_usuario_activo(p_usuario_id bigint, p_activo boolean)
returns void language plpgsql set search_path = public as $$
begin
  update usuarios set activo = p_activo where id = p_usuario_id;
  if not p_activo then
    update sesiones set activa = false, cerrada_en = now(), motivo_cierre = 'USUARIO_DESACTIVADO'
     where usuario_id = p_usuario_id and activa;
  end if;
end $$;


-- ---------------------------------------------------------------------
-- Cargas
-- ---------------------------------------------------------------------

-- Crea la carga con todas las motos del archivo, o nada si falla
-- p_carga: {codigo, fecha, destino, placa, conductor, motos: [{articulo, marca, descripcion, referencia}]}
create function app_importar_carga(p_carga jsonb, p_usuario_id bigint, p_archivo text)
returns jsonb language plpgsql set search_path = public as $$
declare
  v_id bigint;
  v_n int;
begin
  insert into cargas (codigo_contrato, fecha, destino, placa_camion, conductor, archivo_origen, creada_por)
  values (p_carga->>'codigo', (p_carga->>'fecha')::date, nullif(p_carga->>'destino', ''),
          nullif(p_carga->>'placa', ''), nullif(p_carga->>'conductor', ''), p_archivo, p_usuario_id)
  returning id into v_id;

  insert into motos_carga (carga_id, articulo, marca, descripcion, referencia)
  select v_id, m->>'articulo', nullif(m->>'marca', ''), nullif(m->>'descripcion', ''), nullif(m->>'referencia', '')
    from jsonb_array_elements(p_carga->'motos') m;
  get diagnostics v_n = row_count;

  return jsonb_build_object('ok', true, 'id', v_id, 'codigo', p_carga->>'codigo', 'motos', v_n);
exception when unique_violation then
  return jsonb_build_object('ok', false, 'error', 'Ya existe una carga con ese código para esa fecha.');
end $$;


-- Inicia la carga o la REANUDA (si estaba pausada o se finalizó incompleta) con una cámara
create function app_iniciar_carga(p_carga_id bigint, p_camara_id bigint)
returns jsonb language plpgsql set search_path = public as $$
declare
  v_estado text;
  v_cam record;
  v_ocupada text;
begin
  select estado into v_estado from cargas where id = p_carga_id for update;
  if v_estado is null then raise exception 'La carga no existe.'; end if;
  if v_estado not in ('PENDIENTE', 'EN_CARGA', 'PAUSADA', 'INCOMPLETA') then
    raise exception 'La carga está % y no se puede iniciar ni reanudar.', v_estado;
  end if;

  select id, nombre, fuente into v_cam from camaras where id = p_camara_id and activa;
  if v_cam.id is null then raise exception 'La cámara no existe o está desactivada.'; end if;
  select codigo_contrato into v_ocupada from cargas
   where camara_id = p_camara_id and estado = 'EN_CARGA' and id <> p_carga_id limit 1;
  if v_ocupada is not null then
    raise exception 'La cámara "%" está en uso por la carga %.', v_cam.nombre, v_ocupada;
  end if;

  update cargas
     set estado = 'EN_CARGA', iniciada_en = coalesce(iniciada_en, now()), camara_id = p_camara_id,
         finalizada_en = null, finalizada_por = null
   where id = p_carga_id;
  return jsonb_build_object('id', v_cam.id, 'nombre', v_cam.nombre, 'fuente', v_cam.fuente);
end $$;


-- Pausar (EN_CARGA -> PAUSADA) o cancelar una carga
create function app_cambiar_estado(p_carga_id bigint, p_nuevo text, p_permitidos text[])
returns jsonb language plpgsql set search_path = public as $$
declare
  v_id bigint;
  v_camara bigint;
begin
  update cargas set estado = p_nuevo
   where id = p_carga_id and estado = any(p_permitidos)
  returning id, camara_id into v_id, v_camara;
  if v_id is null then raise exception 'No se puede cambiar el estado de esta carga.'; end if;
  return jsonb_build_object('id', v_id, 'camara_id', v_camara);
end $$;


-- QR leído por la cámara. Resultados:
--   VALIDA       moto pendiente de esta carga -> queda CARGADA
--   DUPLICADA    QR ya usado: esa moto ya está cargada en el camión
--   SOBRANTE     la referencia es de esta carga pero ya se cargaron todas sus unidades
--   OTRA_CARGA   la moto es de otra carga abierta -> ¡no debe subir a este camión!
--   NO_PERTENECE el QR no coincide con ninguna moto
create function app_registrar_lectura(
  p_carga_id bigint, p_contenido text, p_candidatos text[],
  p_camara_id bigint default null, p_evidencia text default null, p_track_id text default null)
returns jsonb language plpgsql set search_path = public as $$
declare
  v_carga record;
  v_moto record;
  v_otra record;
  v_moto_id bigint;
  v_resultado text;
  v_mensaje text;
  v_tipo text;
  v_severidad text;
  v_titulo text;
begin
  select id, codigo_contrato, estado into v_carga from cargas where id = p_carga_id for update;
  if v_carga.id is null then raise exception 'La carga no existe.'; end if;
  if v_carga.estado <> 'EN_CARGA' then
    raise exception 'La carga no está en proceso. Presione "Iniciar carga" o "Reanudar carga".';
  end if;

  -- 1) ¿Este QR ya cargó una moto de esta carga?
  select id, coalesce(descripcion, referencia, articulo) as nombre into v_moto
    from motos_carga where carga_id = p_carga_id and qr_leido = p_contenido limit 1;

  if v_moto.id is not null then
    v_resultado := 'DUPLICADA';
    v_moto_id := v_moto.id;
    v_mensaje := 'QR ya usado y moto ya cargada en el camión: ' || v_moto.nombre;
  else
    -- 2) Una unidad pendiente de ese artículo
    select id, coalesce(descripcion, referencia, articulo) as nombre, articulo into v_moto
      from motos_carga
     where carga_id = p_carga_id and estado = 'PENDIENTE' and articulo = any(p_candidatos)
     order by id limit 1;

    if v_moto.id is not null then
      update motos_carga
         set estado = 'CARGADA', cargada_en = now(), qr_leido = p_contenido, track_id = p_track_id
       where id = v_moto.id;
      v_resultado := 'VALIDA';
      v_moto_id := v_moto.id;
      v_mensaje := v_moto.nombre || ' · ' || v_moto.articulo || ' cargada al camión';
    else
      -- 3) El artículo es de esta carga pero ya se cargaron todas sus unidades
      select coalesce(descripcion, referencia, articulo) as nombre into v_moto
        from motos_carga where carga_id = p_carga_id and articulo = any(p_candidatos) limit 1;

      if v_moto.nombre is not null then
        v_resultado := 'SOBRANTE';
        v_mensaje := '¡SOBRA UNA MOTO! Ya se cargaron todas las unidades de ' || v_moto.nombre || ' que pide la carga';
        v_tipo := 'MOTO_SOBRANTE';
        v_severidad := 'ALTA';
        v_titulo := 'Moto de más en el camión de ' || v_carga.codigo_contrato;
      else
        -- 4) ¿Es de otra carga abierta?
        select coalesce(m.descripcion, m.referencia, m.articulo) as nombre, m.articulo, c.codigo_contrato, c.destino
          into v_otra
          from motos_carga m join cargas c on c.id = m.carga_id
         where c.id <> p_carga_id and c.estado in ('PENDIENTE', 'EN_CARGA', 'PAUSADA')
           and m.articulo = any(p_candidatos)
         order by c.fecha desc limit 1;

        if v_otra.codigo_contrato is not null then
          v_resultado := 'OTRA_CARGA';
          v_mensaje := '¡NO SUBIR! ' || v_otra.nombre || ' · ' || v_otra.articulo || ' pertenece a la carga '
                       || v_otra.codigo_contrato || ' (' || coalesce(v_otra.destino, 'sin destino') || ')';
          v_tipo := 'MOTO_OTRA_CARGA';
          v_severidad := 'ALTA';
          v_titulo := 'Moto de otra carga en el camión de ' || v_carga.codigo_contrato;
        else
          v_resultado := 'NO_PERTENECE';
          v_mensaje := 'El QR no corresponde a ninguna moto de esta carga';
          v_tipo := 'QR_NO_PERTENECE';
          v_severidad := 'MEDIA';
          v_titulo := 'QR desconocido en la carga ' || v_carga.codigo_contrato;
        end if;
      end if;
    end if;
  end if;

  -- Si YOLO ya había registrado esa moto como "sin identificar", ahora queda identificada
  if p_track_id is not null then
    update detecciones_yolo
       set estado = 'IDENTIFICADA', qr_contenido = p_contenido, moto_carga_id = coalesce(v_moto_id, moto_carga_id)
     where carga_id = p_carga_id and track_id = p_track_id;
  end if;

  insert into lecturas_qr (carga_id, camara_id, moto_carga_id, contenido, resultado, track_id, evidencia)
  values (p_carga_id, p_camara_id, v_moto_id, p_contenido, v_resultado, p_track_id,
          case when v_resultado = 'DUPLICADA' then null else p_evidencia end);

  -- Una sola alerta por el mismo QR cada 10 minutos
  if v_tipo is not null and not exists (
       select 1 from alertas where carga_id = p_carga_id and tipo = v_tipo
          and detalle->>'contenido' = p_contenido and creada_en > now() - interval '10 minutes') then
    insert into alertas (carga_id, tipo, severidad, titulo, mensaje, detalle)
    values (p_carga_id, v_tipo, v_severidad, v_titulo, v_mensaje,
            jsonb_build_object('contenido', p_contenido, 'evidencia', p_evidencia));
  end if;

  return jsonb_build_object('resultado', v_resultado, 'mensaje', v_mensaje, 'moto_id', v_moto_id);
end $$;


-- Moto que YOLO siguió hasta que salió de la imagen.
-- Sin QR asociado -> SIN_IDENTIFICAR + alerta (una moto subió sin control).
create function app_registrar_deteccion(
  p_carga_id bigint, p_camara_id bigint, p_track_id text, p_confianza numeric, p_fotogramas int,
  p_primera timestamptz, p_ultima timestamptz, p_qr text default null, p_evidencia text default null)
returns jsonb language plpgsql set search_path = public as $$
declare
  v_carga record;
  v_lectura record;
  v_estado text;
  v_id bigint;
begin
  select id, codigo_contrato, estado into v_carga from cargas where id = p_carga_id;
  if v_carga.id is null or v_carga.estado <> 'EN_CARGA' then
    return jsonb_build_object('estado', 'IGNORADA');
  end if;

  select contenido, moto_carga_id into v_lectura from lecturas_qr
   where carga_id = p_carga_id and track_id = p_track_id
   order by (resultado = 'VALIDA') desc, leida_en desc limit 1;
  v_estado := case when coalesce(p_qr, v_lectura.contenido) is not null then 'IDENTIFICADA' else 'SIN_IDENTIFICAR' end;

  insert into detecciones_yolo (carga_id, camara_id, track_id, confianza, fotogramas, primera_vez, ultima_vez,
                                qr_contenido, moto_carga_id, estado, evidencia)
  values (p_carga_id, p_camara_id, p_track_id, p_confianza, p_fotogramas, p_primera, p_ultima,
          coalesce(p_qr, v_lectura.contenido), v_lectura.moto_carga_id, v_estado,
          case when v_estado = 'SIN_IDENTIFICAR' then p_evidencia end)  -- solo se guarda la foto si no se identificó
  on conflict (carga_id, track_id) do update
     set ultima_vez   = excluded.ultima_vez,
         fotogramas   = greatest(detecciones_yolo.fotogramas, excluded.fotogramas),
         confianza    = greatest(detecciones_yolo.confianza, excluded.confianza),
         qr_contenido = coalesce(detecciones_yolo.qr_contenido, excluded.qr_contenido),
         estado       = case when detecciones_yolo.estado = 'IDENTIFICADA' then 'IDENTIFICADA' else excluded.estado end
  returning id, estado into v_id, v_estado;

  if v_estado = 'SIN_IDENTIFICAR' then
    insert into alertas (carga_id, tipo, severidad, titulo, mensaje, detalle)
    values (p_carga_id, 'MOTO_SIN_IDENTIFICAR', 'ALTA',
            'Moto sin identificar en el camión de ' || v_carga.codigo_contrato,
            'La cámara vio pasar una moto (seguimiento ' || p_track_id || ') pero no se leyó su QR. '
            || 'Revise la foto y verifique esa moto antes de despachar.',
            jsonb_build_object('track_id', p_track_id, 'confianza', p_confianza, 'evidencia', p_evidencia));
  end if;

  return jsonb_build_object('estado', v_estado, 'id', v_id);
end $$;


-- Cierra la carga comparando con el archivo; si faltan motos queda INCOMPLETA + alerta CRÍTICA
create function app_finalizar_carga(p_carga_id bigint, p_usuario_id bigint)
returns jsonb language plpgsql set search_path = public as $$
declare
  v_carga record;
  v_total int;
  v_faltantes jsonb;
  v_n int;
  v_estado text;
  v_alerta bigint;
  v_yolo int;
  v_sin_id int;
begin
  select * into v_carga from cargas where id = p_carga_id for update;
  if v_carga.id is null then raise exception 'La carga no existe.'; end if;
  if v_carga.estado <> 'EN_CARGA' then
    raise exception 'Solo se puede finalizar una carga que está en proceso.';
  end if;

  select count(*), count(*) filter (where estado = 'SIN_IDENTIFICAR') into v_yolo, v_sin_id
    from detecciones_yolo where carga_id = p_carga_id;
  select count(*) into v_total from motos_carga where carga_id = p_carga_id;
  select coalesce(jsonb_agg(jsonb_build_object('articulo', articulo, 'marca', marca, 'descripcion', descripcion,
                                               'referencia', referencia) order by id), '[]'::jsonb)
    into v_faltantes
    from motos_carga where carga_id = p_carga_id and estado = 'PENDIENTE';
  v_n := jsonb_array_length(v_faltantes);
  v_estado := case when v_n > 0 then 'INCOMPLETA' else 'COMPLETA' end;

  update cargas set estado = v_estado, finalizada_en = now(), finalizada_por = p_usuario_id where id = p_carga_id;

  if v_n > 0 then
    insert into alertas (carga_id, tipo, severidad, titulo, mensaje, detalle)
    values (p_carga_id, 'MOTOS_FALTANTES', 'CRITICA',
            format('Faltaron %s de %s motos en la carga %s', v_n, v_total, v_carga.codigo_contrato),
            format('La carga %s (destino %s, camión %s) se finalizó con %s de %s motos. NO se subieron %s motos.',
                   v_carga.codigo_contrato, coalesce(v_carga.destino, '—'), coalesce(v_carga.placa_camion, '—'),
                   v_total - v_n, v_total, v_n),
            jsonb_build_object('total', v_total, 'cargadas', v_total - v_n, 'faltantes', v_faltantes,
                               'yolo_detectadas', v_yolo, 'yolo_sin_identificar', v_sin_id))
    returning id into v_alerta;
  end if;

  return jsonb_build_object('estado', v_estado, 'faltantes', v_n, 'total', v_total, 'alerta_id', v_alerta,
                            'camara_id', v_carga.camara_id, 'yolo_detectadas', v_yolo, 'yolo_sin_identificar', v_sin_id);
end $$;


-- Todo lo que la pantalla de una carga necesita, en una sola consulta (se llama cada 2 s)
create function app_estado_carga(p_carga_id bigint)
returns jsonb language sql stable set search_path = public as $$
  select jsonb_build_object(
    'estado', r.estado,
    'camara_id', r.camara_id,
    'total', r.total_motos,
    'cargadas', r.motos_cargadas,
    'faltantes', r.motos_faltantes,
    'motos_cargadas', coalesce((
        select jsonb_object_agg(m.id::text, jsonb_build_object('hora', m.cargada_en, 'track', m.track_id))
          from motos_carga m where m.carga_id = r.id and m.estado = 'CARGADA'), '{}'::jsonb),
    'yolo', (select jsonb_build_object(
               'detectadas', count(*),
               'identificadas', count(*) filter (where d.estado = 'IDENTIFICADA'),
               'sin_identificar', count(*) filter (where d.estado = 'SIN_IDENTIFICAR'))
             from detecciones_yolo d where d.carga_id = r.id),
    'lecturas', coalesce((
        select jsonb_agg(to_jsonb(x) order by x.leida_en desc)
          from (select l.id, l.contenido, l.resultado, l.track_id, l.evidencia, l.leida_en,
                       m.articulo, coalesce(m.descripcion, m.referencia) as descripcion
                  from lecturas_qr l left join motos_carga m on m.id = l.moto_carga_id
                 where l.carga_id = r.id
                 order by l.leida_en desc
                 limit 15) x), '[]'::jsonb))
  from v_resumen_cargas r
  where r.id = p_carga_id;
$$;


-- =====================================================================
-- SEGURIDAD
-- Solo el backend (clave SECRETA, rol service_role) lee y escribe.
-- RLS activo sin políticas + sin permisos para anon/authenticated: con la
-- clave pública nadie puede leer tablas ni ejecutar funciones.
-- =====================================================================
alter table usuarios         enable row level security;
alter table super_admin      enable row level security;
alter table sesiones         enable row level security;
alter table camaras          enable row level security;
alter table cargas           enable row level security;
alter table motos_carga      enable row level security;
alter table lecturas_qr      enable row level security;
alter table detecciones_yolo enable row level security;
alter table alertas          enable row level security;

do $$
declare
  f record;
  hay_supabase boolean := exists (select 1 from pg_roles where rolname = 'anon');
begin
  for f in select p.oid::regprocedure as firma
             from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname = 'public' and p.proname like 'app\_%' loop
    execute format('revoke execute on function %s from public', f.firma);
    if hay_supabase then
      execute format('revoke execute on function %s from anon, authenticated', f.firma);
      execute format('grant execute on function %s to service_role', f.firma);
    end if;
  end loop;

  if hay_supabase then
    revoke all on usuarios, super_admin, sesiones, camaras, cargas, motos_carga, lecturas_qr, detecciones_yolo,
                  alertas, v_resumen_cargas, v_cargas, v_alertas, v_usuarios_admin, v_camaras
      from anon, authenticated;
    grant select, insert, update, delete
      on usuarios, sesiones, camaras, cargas, motos_carga, lecturas_qr, detecciones_yolo, alertas to service_role;
    grant select on super_admin to service_role;   -- el backend solo lee el hash
    grant select on v_resumen_cargas, v_cargas, v_alertas, v_usuarios_admin, v_camaras to service_role;
  end if;
end $$;


-- =====================================================================
-- DATOS INICIALES
-- =====================================================================
-- Super administrador "superadmin": solo se guarda el HASH de su clave.
insert into super_admin (usuario, password_hash)
values ('superadmin', 'scrypt:32768:8:1$aj8yjlFGEIonCB3D$3294676a0360de468427eedc1a1629b9d6eafb09838908ec36c61eb92504dfcd229e56235451456715f3182e987ba8b6ba2a3c746136e6d5bf225f9dc197eff3')
on conflict (usuario) do nothing;

-- Cámara inicial: USB 0 (la app cifra la fuente la primera vez que arranca)
insert into camaras (nombre, fuente, ubicacion)
values ('Cámara muelle 1', '0', 'Encima del camión - muelle de carga 1')
on conflict (nombre) do nothing;

-- Que la API de Supabase vea enseguida las funciones y vistas
notify pgrst, 'reload schema';

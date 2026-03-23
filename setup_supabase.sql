-- Cópia y pega esto en el SQL Editor de tu panel de Supabase
-- Esto creará la tabla exacta que el scraper necesita para guardar los datos

create table public.remittance_quotes (
    id uuid default gen_random_uuid() primary key,
    created_at timestamp with time zone default timezone('utc'::text, now()) not null,
    timestamp_scrape text,
    agente text,
    metodo_dispersion text,
    categoria_recaudacion text,
    categoria_dispersion text,
    pais_destino text,
    moneda_origen text,
    moneda_destino text,
    monto_enviado numeric,
    monto_recibido numeric,
    tasa_de_cambio numeric,
    tasa_cambio_normalizada numeric,
    tasa_cambio_final numeric,
    fee_base numeric,
    fee_impuesto numeric,
    total_cobrado numeric,
    metodo_recaudacion text
);

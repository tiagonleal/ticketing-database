BEGIN;

-- 968 bilhetes: um por cada combinação de 3+ zonas (bitmask)
INSERT INTO venda (data_hora, nif_cliente)
SELECT '2026-03-01 12:00:00'::timestamp, NULL
FROM generate_series(1,1023) m
WHERE length(replace((m::bit(10))::text,'0','')) >= 3;

INSERT INTO bilhete (no_venda, desconto, votou)
SELECT no_venda,
       CASE WHEN no_venda % 2 = 0 THEN 0.50 ELSE 0.00 END,
       (no_venda % 4 <> 0)
FROM venda;

INSERT INTO acesso (bid, id_zona)
SELECT b.bid, z.id_zona
FROM (SELECT row_number() OVER (ORDER BY m) AS rn, m
      FROM generate_series(1,1023) m
      WHERE length(replace((m::bit(10))::text,'0','')) >= 3) c
JOIN bilhete b ON b.bid = c.rn
JOIN zona z ON get_bit(c.m::bit(10), z.id_zona - 1) = 1;

-- BULK: 1000 bilhetes/dia útil, 4000/dia fim-de-semana
INSERT INTO venda (data_hora, nif_cliente)
SELECT d + (random()*86399)*interval '1 second',
       CASE WHEN random()<0.6 THEN lpad((floor(random()*1000000000))::bigint::text,9,'0') ELSE NULL END
FROM generate_series('2026-01-01'::timestamp,'2026-06-11'::timestamp,'1 day') d,
     generate_series(1, CASE WHEN extract(dow FROM d) IN (0,6) THEN 4000 ELSE 1000 END) g;

INSERT INTO bilhete (no_venda, desconto, votou)
SELECT v.no_venda,
       CASE WHEN random()<0.5 THEN 0.50 ELSE 0.00 END,
       random()<0.78
FROM venda v WHERE v.no_venda > 968;

INSERT INTO acesso (bid, id_zona)
SELECT b.bid, ((b.bid+k)%10)+1
FROM bilhete b, generate_series(0,2) k WHERE b.bid > 968;

INSERT INTO acesso (bid, id_zona)
SELECT b.bid, z.id_zona FROM bilhete b, zona z
WHERE b.bid > 968 AND random()<0.3 ON CONFLICT DO NOTHING;

INSERT INTO acesso (bid, id_zona)
SELECT b.bid, z.id_zona FROM bilhete b, zona z
WHERE b.bid > 968 AND b.bid % 50 = 0 ON CONFLICT DO NOTHING;

-- VOTOS: soma = nº bilhetes votou; distribuído pelos 180 recintos
UPDATE recinto r
SET votos = sub.base + CASE WHEN sub.rn <= sub.resto THEN 1 ELSE 0 END
FROM (SELECT r2.id_recinto,
             row_number() OVER (ORDER BY r2.id_recinto) AS rn,
             (SELECT count(*) FROM bilhete WHERE votou)/180 AS base,
             (SELECT count(*) FROM bilhete WHERE votou)%180 AS resto
      FROM recinto r2) sub
WHERE r.id_recinto = sub.id_recinto;

COMMIT;
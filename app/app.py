#!/usr/bin/python3
import os
from logging.config import dictConfig

from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from psycopg.rows import namedtuple_row
from psycopg_pool import ConnectionPool


dictConfig(
    {
        "version": 1,
        "formatters": {
            "default": {
                "format": "[%(asctime)s] %(levelname)s in %(module)s:%(lineno)s - %(funcName)20s(): %(message)s",
            }
        },
        "handlers": {
            "wsgi": {
                "class": "logging.StreamHandler",
                "stream": "ext://flask.logging.wsgi_errors_stream",
                "formatter": "default",
            }
        },
        "root": {"level": "INFO", "handlers": ["wsgi"]},
    }
)

RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")

app = Flask(__name__)
app.config.from_prefixed_env()
log = app.logger
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri=RATELIMIT_STORAGE_URI,
)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgres://app:app@postgres/app")

pool = ConnectionPool(
    conninfo=DATABASE_URL,
    kwargs={
        "autocommit": True,
        "row_factory": namedtuple_row,
    },
    min_size=4,
    max_size=10,
    open=True,
    name="postgres_pool",
    timeout=5,
)


@app.route("/zona/<int:zona>/", methods=("GET",))
@limiter.limit("1 per second")
def zona_index(zona):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id_zona FROM zona WHERE id_zona = %(zona)s;",
                {"zona": zona},
            )
            if cur.fetchone() is None:
                return jsonify({"message": "Zona não encontrada.", "status": "error"}), 404

            rows = cur.execute(
                """
                SELECT
                    r.id_recinto,
                    e.nome_cientifico,
                    e.nome_comum,
                    COUNT(a.id_animal) AS num_animais
                FROM recinto r
                LEFT JOIN animal a ON a.id_recinto = r.id_recinto
                LEFT JOIN especie e ON e.nome_cientifico = a.nome_cientifico
                WHERE r.id_zona = %(zona)s
                GROUP BY r.id_recinto, e.nome_cientifico, e.nome_comum
                ORDER BY r.id_recinto, e.nome_cientifico;
                """,
                {"zona": zona},
            ).fetchall()

    recintos = {}
    for row in rows:
        rid = row.id_recinto
        if rid not in recintos:
            recintos[rid] = {"id_recinto": rid, "especies": []}
        if row.nome_cientifico is not None:
            recintos[rid]["especies"].append({
                "nome_cientifico": row.nome_cientifico,
                "nome_comum": row.nome_comum,
                "num_animais": row.num_animais,
            })

    return jsonify(list(recintos.values())), 200


@app.route("/recinto/<int:recinto>/voto/<int:bilhete>/", methods=("POST",))
@limiter.limit("1 per second")
def recinto_voto_save(recinto, bilhete):
    with pool.connection() as conn:
        with conn.cursor() as cur:
            with conn.transaction():
                cur.execute(
                    "SELECT votou FROM bilhete WHERE bid = %(bid)s FOR UPDATE;",
                    {"bid": bilhete},
                )
                row = cur.fetchone()
                if row is None:
                    return jsonify({"message": "Bilhete não encontrado.", "status": "error"}), 404
                if row.votou:
                    return jsonify({"message": "Este bilhete já votou.", "status": "error"}), 409

                cur.execute(
                    """
                    SELECT 1
                    FROM acesso ac
                    JOIN recinto r ON r.id_zona = ac.id_zona
                    WHERE ac.bid = %(bid)s
                      AND r.id_recinto = %(recinto)s;
                    """,
                    {"bid": bilhete, "recinto": recinto},
                )
                if cur.fetchone() is None:
                    return jsonify({"message": "O recinto não pertence a uma zona acessível por este bilhete.", "status": "error"}), 403

                cur.execute(
                    "UPDATE bilhete SET votou = TRUE WHERE bid = %(bid)s;",
                    {"bid": bilhete},
                )
                cur.execute(
                    "UPDATE recinto SET votos = votos + 1 WHERE id_recinto = %(recinto)s;",
                    {"recinto": recinto},
                )

    return jsonify({"message": "Voto registado com sucesso.", "status": "success"}), 200


@app.route("/venda/", methods=("POST",))
@limiter.limit("1 per second")
def venda_save():
    body = request.get_json()

    if not body or "bilhetes" not in body:
        return jsonify({"message": "Lista de bilhetes obrigatória.", "status": "error"}), 400

    nif = body.get("nif", None)
    bilhetes_input = body["bilhetes"]

    if not bilhetes_input:
        return jsonify({"message": "Tem de haver pelo menos um bilhete.", "status": "error"}), 400

    try:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                with conn.transaction():
                    cur.execute(
                        """
                        INSERT INTO venda (data_hora, nif_cliente)
                        VALUES (NOW(), %(nif)s)
                        RETURNING no_venda;
                        """,
                        {"nif": nif},
                    )
                    no_venda = cur.fetchone().no_venda

                    total = 0.0
                    resultado_bilhetes = []

                    for b in bilhetes_input:
                        zonas = b.get("zonas", [])
                        desconto = b.get("desconto", 0.0)

                        if not zonas:
                            raise ValueError("Cada bilhete precisa de pelo menos uma zona de acesso.")
                        if not (0.0 <= float(desconto) <= 1.0):
                            raise ValueError("Desconto deve estar entre 0 e 1.")

                        cur.execute(
                            """
                            INSERT INTO bilhete (no_venda, desconto, votou)
                            VALUES (%(no_venda)s, %(desconto)s, FALSE)
                            RETURNING bid;
                            """,
                            {"no_venda": no_venda, "desconto": desconto},
                        )
                        bid = cur.fetchone().bid
                        preco_bilhete = 0.0

                        for id_zona in zonas:
                            cur.execute(
                                "SELECT preco FROM zona WHERE id_zona = %(id_zona)s;",
                                {"id_zona": id_zona},
                            )
                            zona_row = cur.fetchone()
                            if zona_row is None:
                                raise ValueError(f"Zona {id_zona} não existe.")

                            cur.execute(
                                """
                                INSERT INTO acesso (bid, id_zona)
                                VALUES (%(bid)s, %(id_zona)s);
                                """,
                                {"bid": bid, "id_zona": id_zona},
                            )
                            preco_bilhete += float(zona_row.preco) * (1.0 - float(desconto))

                        total += preco_bilhete
                        resultado_bilhetes.append({
                            "bid": bid,
                            "preco": round(preco_bilhete, 2),
                        })

        return jsonify({
            "no_venda": no_venda,
            "total": round(total, 2),
            "bilhetes": resultado_bilhetes,
        }), 201

    except ValueError as e:
        return jsonify({"message": str(e), "status": "error"}), 400
    except Exception as e:
        log.error(f"Erro na venda: {e}")
        return jsonify({"message": "Erro interno no servidor.", "status": "error"}), 500


@app.route("/ping", methods=("GET",))
@limiter.exempt
def ping():
    return jsonify({"message": "pong!", "status": "success"})


if __name__ == "__main__":
    app.run()
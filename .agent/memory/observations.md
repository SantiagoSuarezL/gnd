# Observations — Game Network Diagnostics (GND)

> Observaciones de red/comportamiento en curso, no resueltas todavía.
> Cuando una observación se resuelve y queda blindada en código: mover
> a `observations_archive.md` y dejar solo una línea de cierre acá
> apuntando a la Regla de Oro correspondiente.

## En curso

### Infraestructura regional LoL: por qué solo NA1/EUW1 tienen hostnames Riot-direct (post-Fase 14.0a)

**Contexto:** verificación DNS empírica 2026-07-30 (ver `lessons_learned.md`
Regla 14.0a.1) contra 22 candidatos de patrones `lq.<platformId>.lol.
riotgames.com`, `lq.<short>.lol.riotgames.com`, `chat.<platformId>.
lol.riotgames.com` etc. Resultado: solo NA1 (`lq.na.` y `chat.na1.`) y
EUW1 (`lq.eu.`) resuelven a IPs del ASN de Riot (66.151.54.141,
216.133.234.21, 64.7.194.21). Las demás regiones (LA1, LA2, BR, TR,
RU, KR) resuelven a Cloudflare anycast (`104.16.x`) — el mismo proxy
genérico que ya teníamos con `auth.riotgames.com`. EUNE/JP1/OC1/LAN/LAS
/SEA/LAN alt/LAS alt son NXDOMAIN (no resuelven ni a CF, no existen).

**Hipótesis no confirmada (no bloqueante para 14.0a):** Riot
consolidó la infraestructura regional pequeña (LATAM, TR, RU,
KR, JP) detrás de Cloudflare-anycast como edge frontal, pero
mantiene edges propios en los 2 grandes clásicos (NA y EUW). Evidencia
circunstancial: gist histórico de la comunidad (Pulgafree "LAS_Network
_Diagnostic.bat") taguea `lq.la2.lol.riotgames.com` como "Riot-direct"
con IPs 138.0.12.x (datacenter Santiago, ASN Riot) — y hoy resuelve a
`104.16.55.40`/`104.16.56.40` (Cloudflare). El gist quedó
desactualizado tras una migración de infra que Riot no anunció
públicamente.

**Por qué no es confirmable sin Riot:** no hay statement oficial de
Riot sobre migración de infraestructura de"sync endpoints" (la
comunidad descubrió los hostnames vía ingeniería inversa de logs
de `LeagueClientUx.exe` y capturas Wireshark de captura de traffic
de NAT-punch). Confirmar requeriría diff histórico de DNS (ej.
SecurityTrails) para ver cuándo migraron `lq.la2` de Riot-direct a CF,
o capturas Wireshark recientes que muestren hacia dónde enruta el
cliente realmente hoy. No lo vale el costo ahora — no bloquea Fase 14.

**Relevancia para futuras fases:** no tienen action item en 14.0a-h.
Si en una Fase 14.0b futura alguien quiere revivir el tier
`regional_edge`, antes de meter hostnames al mapping debe repetir
la verificación DNS empírica (Regla 14.0a.1) — los patrones publicados
hace 2-3 años no son verdad presente. Si la comunidad reporta nuevos
hostnames Riot-direct para regiones específicas, separar "Riot
labeled" (DNS name.apunta a Cloudflare) de "Riot-direct" (IP del ASN
Riot); solo el segundo aporta signal nueva en medición.

### Diseño: Ponderación de DNS genéricos bajo VPN (post-Fase 13 sesión 3)

**Contexto:** validación in-vivo de WARP Comparison con warp-cli
2026.6.850.0 (2026-07-30). Cuando WARP está ON, Google (8.8.8.8) y
Quad9 (9.9.9.9) empeoran sustancialmente porque todo el tráfico se
enruta por el túnel de Cloudflare, dejando de usar las rutas directas
optimizadas de cada DNS al datacenter del usuario. riot_public (al
datacenter Riot) es lo que el usuario prende WARP para mejorar, no los
DNS genéricos.

**Comportamiento observado:** en la corrida del usuario, Google y
Quad9 mostraron empeoramiento de latencia significativo bajo WARP.
Esto entra al verdict y los provider_deltas como "empeora en google,
quad9". El score global ponderado puede degradarse artificialmente
aunque el target de juego (riot_public) mejore.

**Discusión de diseño (no es bug — usuario abrió explícitamente):**
¿El score/verdict agregado debería ponderar distinto providers de DNS
genéricos bajo VPN vs el target de juego real?

Opciones posibles (a evaluar en fase futura):
1. Mantener comportamiento actual — el score global refleja TODO, el
   usuario ve provider_deltas y decide.
2. Sub-pesificar providers "no-target" bajo VPN (factor 0.5 cuando
   WARP on) para no contaminar el verdict cuando el target mejoró.
3. Veredicto dual: "global" + "target-only" (sólo riot_public +
   riot_game_server). El usuario ve dos veredictos y decide cuál le
   importa.

**Estado:** NO es bug, NO se va a fixear en esta sesión. Anotado acá
para que la próxima sesión de diseño tenga el contexto cuando se
discuta. Decisión del usuario: dejar el comportamiento actual y
re-discutir si WARP es una feature que el usuario va a usar
frecuentemente (hoy es ocasional).

**Validación:** el usuario confirmó que la lógica de comparación en sí
funciona bien — riot_public 82.2ms→63.2ms (-23.1%) coincide con su
experiencia real reportada de 90ms→65-70ms. La mejora existe; el
problema es solo de ponderación agregada bajo VPN.

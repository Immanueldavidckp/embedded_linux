/* Multi-layer grid A* for the maze router (tools/maze_route.py).
 *
 * The grid is a window of the board: L layers x H rows x W cols, one byte per
 * cell. Python builds the masks (obstacles already dilated by clearance + half
 * the track width), C only searches.
 *
 *   blocked[l][y][x]  1 = the track centre may not be here
 *   padok[l][y][x]    1 = a via pad (D/2 + clearance) fits on layer l here
 *   holeok[y][x]      1 = a via drill fits here (hole-to-hole, hole-to-copper)
 *   st[l][y][x]       1 = source cell, 2 = target cell
 *   lcost[l]          cost multiplier per layer (0 = layer not allowed)
 *   pen[l][y][x]      extra cost (x pen_unit) for entering a cell: rip-up mode, where
 *                     other nets' routed copper is crossable at a price (NULL = none)
 *   vpen[y][x]        same for placing a via here (NULL = none)
 *
 * A layer change at (y,x) is a through via: allowed when holeok and padok on
 * both the departure and arrival layers. Returns the path length (cells) and
 * writes (l, y, x) triplets target->source into out, or -1 if no path.
 */
#include <stdint.h>
#include <stdlib.h>
#include <math.h>
#include <string.h>

typedef struct { float f; int32_t i; } hnode;
static hnode *heap; static long hn, hcap;

static void hpush(float f, int32_t i) {
    if (hn == hcap) { hcap = hcap ? hcap * 2 : 1 << 16; heap = realloc(heap, hcap * sizeof(hnode)); }
    long k = hn++;
    while (k) { long p = (k - 1) >> 1; if (heap[p].f <= f) break; heap[k] = heap[p]; k = p; }
    heap[k].f = f; heap[k].i = i;
}
static hnode hpop(void) {
    hnode top = heap[0], last = heap[--hn];
    long k = 0;
    for (;;) {
        long c = 2 * k + 1; if (c >= hn) break;
        if (c + 1 < hn && heap[c + 1].f < heap[c].f) c++;
        if (heap[c].f >= last.f) break;
        heap[k] = heap[c]; k = c;
    }
    heap[k] = last; return top;
}

static inline float hdist(int y, int x, int ty0, int tx0, int ty1, int tx1) {
    int dx = x < tx0 ? tx0 - x : (x > tx1 ? x - tx1 : 0);
    int dy = y < ty0 ? ty0 - y : (y > ty1 ? y - ty1 : 0);
    int mn = dx < dy ? dx : dy, mx = dx < dy ? dy : dx;
    return mx + 0.41421356f * mn;
}

int astar(int L, int H, int W, const uint8_t *blocked, const uint8_t *padok, const uint8_t *holeok,
          const uint8_t *st, const float *lcost, float via_cost, float bend_cost,
          int ty0, int tx0, int ty1, int tx1, int32_t *out, int maxout, long max_expand,
          const uint8_t *pen, const uint8_t *vpen, float pen_unit)
{
    long N = (long)L * H * W, HW = (long)H * W;
    float *g = malloc(N * sizeof(float));
    int32_t *par = malloc(N * sizeof(int32_t));
    uint8_t *closed = calloc(N, 1);
    if (!g || !par || !closed) { free(g); free(par); free(closed); return -2; }
    float minl = 1e9f;
    for (int l = 0; l < L; l++) if (lcost[l] > 0 && lcost[l] < minl) minl = lcost[l];
    for (long i = 0; i < N; i++) { g[i] = INFINITY; par[i] = -1; }
    hn = 0;
    for (long i = 0; i < N; i++)
        if (st[i] == 1 && !blocked[i] && lcost[i / HW] > 0) {
            g[i] = 0; int y = (i % HW) / W, x = i % W;
            hpush(hdist(y, x, ty0, tx0, ty1, tx1) * minl, (int32_t)i);
        }
    static const int DX[8] = {1, -1, 0, 0, 1, 1, -1, -1}, DY[8] = {0, 0, 1, -1, 1, -1, 1, -1};
    long found = -1, expanded = 0;
    while (hn) {
        hnode nd = hpop(); long i = nd.i;
        if (closed[i]) continue;
        closed[i] = 1;
        if (st[i] == 2) { found = i; break; }
        if (++expanded > max_expand) break;
        int l = i / HW, y = (i % HW) / W, x = i % W;
        float gi = g[i], lc = lcost[l];
        long pi = par[i]; int pdx = 0, pdy = 0;
        if (pi >= 0 && pi / HW == l) { pdx = x - (int)(pi % W); pdy = y - (int)((pi % HW) / W); }
        for (int d = 0; d < 8; d++) {
            int nx = x + DX[d], ny = y + DY[d];
            if (nx < 0 || ny < 0 || nx >= W || ny >= H) continue;
            long j = (long)l * HW + (long)ny * W + nx;
            if (blocked[j] || closed[j]) continue;
            float c = (d < 4 ? 1.0f : 1.41421356f) * lc;
            if (pi >= 0 && (pdx != DX[d] || pdy != DY[d])) c += bend_cost;
            if (pen) c += pen[j] * pen_unit;
            float ng = gi + c;
            if (ng < g[j]) { g[j] = ng; par[j] = (int32_t)i; hpush(ng + hdist(ny, nx, ty0, tx0, ty1, tx1) * minl, (int32_t)j); }
        }
        long cell = (long)y * W + x;
        if (holeok[cell] && padok[i]) {
            for (int m = 0; m < L; m++) {
                if (m == l || lcost[m] <= 0) continue;
                long j = (long)m * HW + cell;
                if (blocked[j] || closed[j] || !padok[j]) continue;
                float ng = gi + via_cost + (vpen ? vpen[cell] * pen_unit : 0.0f);
                if (ng < g[j]) { g[j] = ng; par[j] = (int32_t)i; hpush(ng + hdist(y, x, ty0, tx0, ty1, tx1) * minl, (int32_t)j); }
            }
        }
    }
    int n = -1;
    if (found >= 0) {
        n = 0;
        for (long k = found; k >= 0 && n < maxout; k = par[k]) {
            out[3 * n] = k / HW; out[3 * n + 1] = (k % HW) / W; out[3 * n + 2] = k % W; n++;
        }
    }
    free(g); free(par); free(closed);
    return n;
}

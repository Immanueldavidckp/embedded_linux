"""The board stackup in one place: layer order, thickness, and what each copper layer is for.

Rev A2 is 10 layers. The 8-layer rev A1 ran out of signal area between the RK3576 and the
LPDDR5 (72 connections the router could not place, LOG.md #31-#33), so two signal layers
were added as dual striplines next to the existing ones:

  L1  F.Cu   SIG  BGA escape, HS pairs        L6  In5.Cu  GND
  L2  In1.Cu GND                              L7  In6.Cu  SIG  DDR CA, low speed
  L3  In2.Cu SIG  DDR byte lanes              L8  In7.Cu  SIG  (new) route orthogonal to L7
  L4  In3.Cu SIG  (new) route orthogonal to L3  L9  In8.Cu  PWR  big rails (5 V, 3V3, 1V8)
  L5  In4.Cu PWR  core / DDR rails             L10 B.Cu   SIG  + decoupling

Each signal layer still has a plane next to it; L3/L4 and L7/L8 are dual striplines, so
long parallel runs on the pair should cross at right angles. Thicknesses are a symmetric
1.6 mm build (JLCPCB 10-layer style); confirm with the fab's impedance calculator before
release: the net-class widths in gen_pcb.py were sized for the 8-layer build.
"""
import pcbnew

STACKUP = [
    ('F.SilkS', 'Top Silk Screen', None, None), ('F.Paste', 'Top Solder Paste', None, None),
    ('F.Mask', 'Top Solder Mask', 0.01, None),
    ('F.Cu', 'copper', 0.035, 'L1 SIG (BGA escape, HS pairs)'),
    ('dielectric 1', 'prepreg', 0.0994, ('3313', 4.10)),
    ('In1.Cu', 'copper', 0.0152, 'L2 GND'),
    ('dielectric 2', 'core', 0.15, ('FR4', 4.60)),
    ('In2.Cu', 'copper', 0.0152, 'L3 SIG (DDR byte lanes)'),
    ('dielectric 3', 'prepreg', 0.13, ('2116', 4.20)),
    ('In3.Cu', 'copper', 0.0152, 'L4 SIG (orthogonal to L3)'),
    ('dielectric 4', 'core', 0.15, ('FR4', 4.60)),
    ('In4.Cu', 'copper', 0.0152, 'L5 PWR (core and DDR rails)'),
    ('dielectric 5', 'prepreg', 0.32, ('7628', 4.40)),
    ('In5.Cu', 'copper', 0.0152, 'L6 GND'),
    ('dielectric 6', 'core', 0.15, ('FR4', 4.60)),
    ('In6.Cu', 'copper', 0.0152, 'L7 SIG (DDR CA, low speed)'),
    ('dielectric 7', 'prepreg', 0.13, ('2116', 4.20)),
    ('In7.Cu', 'copper', 0.0152, 'L8 SIG (orthogonal to L7)'),
    ('dielectric 8', 'core', 0.15, ('FR4', 4.60)),
    ('In8.Cu', 'copper', 0.0152, 'L9 PWR (5 V, 3V3, 1V8)'),
    ('dielectric 9', 'prepreg', 0.0994, ('3313', 4.10)),
    ('B.Cu', 'copper', 0.035, 'L10 SIG + decoupling'),
    ('B.Mask', 'Bottom Solder Mask', 0.01, None), ('B.Paste', 'Bottom Solder Paste', None, None),
    ('B.SilkS', 'Bottom Silk Screen', None, None),
]
COPPER = [n for n, typ, _t, _e in STACKUP if typ == 'copper']
ROLE = {n: e.split()[1].lower() for n, typ, _t, e in STACKUP if typ == 'copper'}   # sig / gnd / pwr
LAYER_COUNT = len(COPPER)
CORE_PWR, BIG_PWR = 'In4.Cu', 'In8.Cu'      # pour.py: local rails / board-wide rails


def lid(name):
    """KiCad layer id for a copper layer name ('In3.Cu' -> pcbnew.In3_Cu)."""
    return getattr(pcbnew, name.replace('.', '_'))


def layers(role=None):
    return [lid(n) for n in COPPER if role is None or ROLE[n] == role]


def stackup_sexp():
    out = ['\t\t(stackup']
    for name, typ, th, extra in STACKUP:
        s = f'\t\t\t(layer "{name}" (type "{typ}")'
        if th is not None:
            s += f' (thickness {th})'
        if typ in ('prepreg', 'core'):
            s += f' (material "{extra[0]}") (epsilon_r {extra[1]}) (loss_tangent 0.02)'
        if 'Mask' in name:
            s += ' (color "Green")'
        if 'SilkS' in name:
            s += ' (color "White")'
        out.append(s + ')')
    out += ['\t\t\t(copper_finish "ENIG")', '\t\t\t(dielectric_constraints no)', '\t\t)']
    return '\n'.join(out)

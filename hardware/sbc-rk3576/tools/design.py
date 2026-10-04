#!/usr/bin/env python3
"""RK3576 SBC - single source of truth for the circuit.

Every part, every pin->net connection, every BOM field lives here. The
schematic, PCB and BOM generators all import `build()` so the three can never
drift apart. Read this file top to bottom like a schematic: one function per
sheet.

Conventions
  * Net names are global (KiCad global labels) and UPPER_CASE.
  * Rails follow Rockchip naming: <NAME>_S0 is off in suspend, _S3 stays on in
    suspend, _S5 is always on whenever input power is present.
  * Reference designators are sheet-scoped: C4xx lives on sheet 04.
  * Prices are 1k-qty USD estimates (LCSC/distributor, Oct 2026) - budgeting only.
"""
import csv, os, re
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')

SHEETS = OrderedDict([
    ('01_power_input', 'USB-C 5V input, protection'),
    ('02_pmic', 'RK806S-5 PMIC'),
    ('03_power_ext', 'Discrete regulators & load switches'),
    ('04_soc_power', 'RK3576 power, ground & decoupling'),
    ('05_soc_system', 'Clock, reset, boot, debug UART, keys, LEDs'),
    ('06_lpddr5', 'LPDDR5 x32 memory'),
    ('07_storage', 'eMMC 5.1 + microSD'),
    ('08_nvme', 'M.2 M-key NVMe (PCIe 2.1 x1)'),
    ('09_hdmi', 'HDMI 2.1 TX (4K)'),
    ('10_usb', 'USB-C OTG (maskrom) + USB 3.0 host'),
    ('11_soc_gpio', 'RK3576 GPIO banks'),
    ('12_mechanical', 'Mounting holes, fiducials'),
])

# --------------------------------------------------------------------- parts
FP_R = {'0201': 'Resistor_SMD:R_0201_0603Metric', '0402': 'Resistor_SMD:R_0402_1005Metric',
        '0603': 'Resistor_SMD:R_0603_1608Metric'}
FP_C = {'0201': 'Capacitor_SMD:C_0201_0603Metric', '0402': 'Capacitor_SMD:C_0402_1005Metric',
        '0603': 'Capacitor_SMD:C_0603_1608Metric', '0805': 'Capacitor_SMD:C_0805_2012Metric'}


class Part:
    def __init__(self, ref, lib_id, value, footprint, nets, sheet, mpn='', mfr='', lcsc='',
                 price=0.0, dnp=False, desc='', unit_sheets=None, bom=True):
        self.ref, self.lib_id, self.value, self.footprint = ref, lib_id, value, footprint
        self.nets = nets                    # pin number -> net name
        self.sheet = sheet
        self.mpn, self.mfr, self.lcsc, self.price = mpn, mfr, lcsc, price
        self.dnp, self.desc = dnp, desc
        self.unit_sheets = unit_sheets or {}  # unit -> sheet (multi-unit symbols)
        self.bom = bom                      # False: board feature, not a purchased part


class Design:
    def __init__(self):
        self.parts = []
        self._cnt = {}
        self.sheet = None
        self.notes = []

    def ref(self, prefix):
        sn = int(self.sheet[:2])
        k = self._cnt.get((prefix, sn), 0) + 1
        self._cnt[(prefix, sn)] = k
        # C401..C499, then C4100.. on a crowded sheet (never collides with C5xx)
        return f'{prefix}{sn * 100 + k}' if k < 100 else f'{prefix}{sn * 1000 + k}'

    def add(self, prefix, lib_id, value, fp, nets, **kw):
        p = Part(kw.pop('ref', None) or self.ref(prefix), lib_id, value, fp, nets, self.sheet, **kw)
        self.parts.append(p)
        return p

    # ---- generic passives
    def R(self, value, a, b, size='0402', tol='1%', **kw):
        price = {'0201': 0.0006, '0402': 0.0005, '0603': 0.0008}[size]
        kw.setdefault('mpn', f'{size} {value} {tol}')
        return self.add('R', 'Device:R', value, FP_R[size], {'1': a, '2': b},
                        mfr=kw.pop('mfr', 'Yageo/UniOhm'), price=price, **kw)

    def C(self, value, a, b='GND', size='0402', volt='6.3V', diel='X5R', **kw):
        price = {('0201',): 0.001, ('0402',): 0.0015, ('0603',): 0.004, ('0805',): 0.01}[(size,)]
        if value in ('22uF', '47uF'):
            price *= 3
        if volt == '6.3V' and any(str(n).startswith(('VCC5V', 'VBUS', 'HDMI_5V')) for n in (a, b)):
            volt = '10V'          # >=2x margin on 5V rails (MLCC DC-bias derating)
        kw.setdefault('mpn', f'{size} {value} {volt} {diel}')
        return self.add('C', 'Device:C', value, FP_C[size], {'1': a, '2': b},
                        mfr=kw.pop('mfr', 'Samsung/Murata'), price=price, **kw)

    def caps(self, net, spec, gnd='GND'):
        """spec: '3x22uF/0603 2x1uF 8x100nF'."""
        for tok in spec.split():
            n, rest = tok.split('x', 1)
            val, _, size = rest.partition('/')
            size = size or ('0603' if val in ('22uF', '47uF', '10uF') else '0402')
            for _ in range(int(n)):
                self.C(val, net, gnd, size=size, volt='10V' if val in ('10uF', '22uF', '47uF', '4.7uF') else '6.3V')

    def L(self, value, a, b, fp, mpn, price, **kw):
        return self.add('L', 'Device:L', value, fp, {'1': a, '2': b}, mpn=mpn, price=price, **kw)


# ---------------------------------------------------------------- SoC lookup
def _read(name):
    return [(r['ball'], r['name']) for r in csv.DictReader(open(os.path.join(DATA, name)))]


SOC_PINS = _read('rk3576_pins.csv')
SOC_NAME = dict(SOC_PINS)


def soc(func):
    """Ball for a function token, e.g. soc('EMMC_D0') or soc('GPIO4_C7')."""
    hits = []
    for ball, name in SOC_PINS:
        parts = name.split('/')
        if func in parts or any(re.fullmatch(re.escape(func) + r'_[udz]', p) for p in parts):
            hits.append(ball)
    assert len(hits) == 1, (func, hits)
    return hits[0]


def soc_family(regex):
    return [b for b, n in SOC_PINS if re.fullmatch(regex, n)]


# ---------------------------------------------------------------- the design
def build():
    d = Design()
    soc_nets = {}            # ball -> net, filled by every sheet, applied at the end

    def S(func, net):
        b = soc(func)
        assert b not in soc_nets, (func, b, soc_nets.get(b))
        soc_nets[b] = net

    # ===================================================== 01 power input
    d.sheet = '01_power_input'
    # USB-C receptacle: power sink (5V/3A via Rd=5.1k) + USB2 OTG0 data for
    # maskrom flashing / ADB. Same port as the "TCU programming port" idea.
    d.add('J', 'Connector:USB_C_Receptacle_USB2.0_16P', 'USB-C PWR/OTG',
          'Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12',
          {'A1': 'GND', 'A12': 'GND', 'B1': 'GND', 'B12': 'GND',
           'A4': 'VBUS_IN', 'A9': 'VBUS_IN', 'B4': 'VBUS_IN', 'B9': 'VBUS_IN',
           'A5': 'USBC_CC1', 'B5': 'USBC_CC2',
           'A6': 'USBC_DP', 'B6': 'USBC_DP', 'A7': 'USBC_DM', 'B7': 'USBC_DM',
           'A8': None, 'B8': None, 'S1': 'GND'},
          mpn='TYPE-C-31-M-12', mfr='Korean Hroparts', lcsc='C165948', price=0.10,
          desc='USB-C 16P receptacle, power in + USB2 OTG0')
    d.R('5.1k', 'USBC_CC1', 'GND', desc='Rd: advertise sink')
    d.R('5.1k', 'USBC_CC2', 'GND', desc='Rd: advertise sink')
    d.add('F', 'Device:Fuse', '6A', 'Fuse:Fuse_1206_3216Metric', {'1': 'VBUS_IN', '2': 'VCC5V0_SYS_S5'},
          mpn='1206L600/8SLY (6A fast)', mfr='Littelfuse/BHFUSE', price=0.06, desc='Input fuse')
    d.add('D', 'Device:D_TVS', 'SMF5.0A', 'Diode_SMD:D_SOD-123F', {'1': 'VCC5V0_SYS_S5', '2': 'GND'},
          mpn='SMF5.0A', mfr='Littelfuse/MDD', lcsc='C123799', price=0.03, desc='5V TVS on VBUS')
    # No reverse-polarity FET: a USB-C source cannot present reversed polarity, and a
    # SOT-23 P-FET would dissipate ~0.5W at 3A. Fuse + TVS is the low-cost choice.
    d.caps('VCC5V0_SYS_S5', '2x47uF/0805 2x10uF/0603 1x100nF')
    d.add('LED', 'Device:LED', 'PWR', 'LED_SMD:LED_0603_1608Metric', {'1': 'LED_PWR_K', '2': 'VCC5V0_SYS_S5'},
          mpn='19-217/GHC-YR1S2/3T', mfr='Everlight', lcsc='C72043', price=0.01, desc='Green power LED')
    d.R('2.2k', 'LED_PWR_K', 'GND')
    d.notes.append('Input is USB-C 5V/3A (Rd sink, no PD negotiation): ~15W budget. '
                   'NVMe + full CPU/NPU load can exceed this; use a 5V/4A+ supply or add a PD controller (rev B).')

    # ===================================================== 02 PMIC
    d.sheet = '02_pmic'
    pm = {}
    rk806 = {int(b): n for b, n in _read('rk806_pins.csv')}
    # buck n: (rail, nominal V, inductor value, inductor fp/mpn/price, out caps)
    L_BIG = ('Inductor_SMD:L_Coilcraft_XAL4030-XXX', 'MDA4030-R24M (0.24uH 8A)', 0.12)
    L_MID = ('Inductor_SMD:L_Coilcraft_XAL4030-XXX', 'MDA4030-R47M (0.47uH 5.5A)', 0.10)
    L_SML = ('Inductor_SMD:L_Changjiang_FNR4030S', 'FNR4030S1R0NT (1uH 3.4A)', 0.05)
    bucks = {
        1: ('VDD_CPU_BIG_S0', '0.85V', '0.24uH', L_BIG, '3x22uF 2x47uF/0805'),
        2: ('VDD_NPU_S0', '0.75V', '0.47uH', L_MID, '3x22uF'),
        3: ('VDD_LOGIC_S0', '0.75V', '0.47uH', L_MID, '3x22uF'),
        4: ('VDD_GPU_S0', '0.85V', '0.47uH', L_MID, '3x22uF'),
        5: ('VDD_CPU_LIT_S0', '0.85V', '1uH', L_SML, '2x22uF'),
        6: ('VDD_DDR_S0', '0.75V', '1uH', L_SML, '2x22uF'),
        7: ('VCC_3V3_S3', '3.3V', '1uH', L_SML, '2x22uF'),
        8: ('VDD2H_DDR_S3', '1.05V', '1uH', L_SML, '2x22uF'),
        9: ('VCC_1V8_S3', '1.8V', '1uH', L_SML, '2x22uF'),
        10: ('VDDQ_DDR_S0', '0.5V', '1uH', L_SML, '2x22uF'),
    }
    for n, name in rk806.items():
        m = re.fullmatch(r'VCC(\d+)(_\d)?', name)
        if m and int(m.group(1)) <= 10:
            pm[str(n)] = 'VCC5V0_SYS_S5'
    for b, (rail, v, lval, lfp, outc) in bucks.items():
        sw = f'PMIC_SW{b}'
        for n, name in rk806.items():
            if re.fullmatch(fr'SW{b}(_\d)?', name):
                pm[str(n)] = sw
            elif name == f'VOUT{b}':
                pm[str(n)] = rail
            elif name == f'FB{b}':
                pm[str(n)] = f'PMIC_FB{b}'
        if f'FB{b}' in rk806.values():
            # Default: remote-sense straight to the rail (internal reference set by
            # RK806S-5 OTP). Divider footprints kept DNP for external-FB mode.
            d.R('0R', f'PMIC_FB{b}', rail, desc=f'BUCK{b} FB sense')
            d.R('DNP', f'PMIC_FB{b}', 'GND', dnp=True, desc=f'BUCK{b} FB divider (optional)')
        d.L(lval, sw, rail, lfp[0], lfp[1], lfp[2], mfr='Sunlord/Changjiang', desc=f'BUCK{b} {rail} {v}')
        d.C('10uF', 'VCC5V0_SYS_S5', size='0603', volt='10V', desc=f'BUCK{b} input')
        d.caps(rail, outc)
    ldos = {   # pin name -> (rail, voltage)
        'PLDO1': ('VCCA_1V8_S0', '1.8V'), 'PLDO2': ('VCCA1V8_PLDO2_S0', '1.8V'),
        'PLDO3': ('VDDA_1V2_S0', '1.2V'), 'PLDO4': ('VCCA_3V3_S0', '3.3V'),
        'PLDO5': ('VCCIO_SD_S0', '3.3V/1.8V'),
        'NLDO1': ('VDD_0V75_S3', '0.75V'), 'NLDO2': ('VDDA_0V85_S0', '0.85V'),
        'NLDO3': ('VDDA_0V75_S0', '0.75V'), 'NLDO4': ('VDDA0V75_HDMI_S0', '0.75V'),
        'NLDO5': ('VDDA_DDR_PLL_S0', '0.85V'),
    }
    for n, name in rk806.items():
        if name in ldos:
            pm[str(n)] = ldos[name][0]
            d.C('2.2uF', ldos[name][0], size='0402', desc=f'{name} {ldos[name][1]} output')
    ldo_in = {'VCC11': 'VCC_2V0_PLDO_S3', 'VCC12': 'VCC5V0_SYS_S5',
              'VCC13': 'VCC_1V1_NLDO_S3', 'VCC14': 'VCC_1V1_NLDO_S3'}
    ctl = {'VCCA': 'VCC5V0_SYS_S5', 'VCCIO': 'VCC_1V8_S3', 'VDC': 'VCC5V0_SYS_S5',
           'PWRON': 'PWRON_L', 'RESETB': 'SYS_RESET_L', 'INT': 'PMIC_INT_L',
           'SCL': 'PMIC_SCL', 'SDA': 'PMIC_SDA', 'CS': 'GND',
           'PWRCTRL1': 'PMIC_PWRCTRL1', 'PWRCTRL2': 'PMIC_PWRCTRL2', 'PWRCTRL3': 'PMIC_PWRCTRL3',
           'EXT_EN': 'PMIC_EXT_EN', 'SYNC': None, 'SYNC_CLK': None, 'EPAD': 'GND'}
    for n, name in rk806.items():
        if name in ldo_in:
            pm[str(n)] = ldo_in[name]
            d.C('4.7uF', ldo_in[name], size='0402', desc=f'{name} LDO input')
        elif name in ctl:
            pm[str(n)] = ctl[name]
    missing = [f'{n}:{v}' for n, v in rk806.items() if str(n) not in pm]
    assert not missing, missing
    d.add('U', 'sbc:RK806S-5', 'RK806S-5', 'Package_DFN_QFN:QFN-68-1EP_8x8mm_P0.4mm_EP5.2x5.2mm_ThermalVias',
          pm, mpn='RK806S-5', mfr='Rockchip', price=2.20, desc='PMIC, OTP preset for RK3576')
    d.caps('VCC_1V8_S3', '1x1uF')
    d.C('1uF', 'VCC5V0_SYS_S5', desc='VCCA filter')
    d.R('2.2k', 'PMIC_SCL', 'VCC_1V8_S3')
    d.R('2.2k', 'PMIC_SDA', 'VCC_1V8_S3')
    d.R('10k', 'PMIC_INT_L', 'VCC_1V8_S3')
    d.R('10k', 'SYS_RESET_L', 'VCC_1V8_S3')
    d.notes.append('RK806S-5 OTP fixes the power-up order of BUCK/LDO slots for RK3576. The '
                   'buck->rail mapping on sheet 02 mirrors the Radxa ROCK 4D reference (also RK806S-5 '
                   '+ RK3576) - re-check against the RK806 datasheet slot table before layout sign-off.')

    # ===================================================== 03 discrete regulators
    d.sheet = '03_power_ext'

    def tps_buck(name, vout_net, vout, rtop, rbot, part='TPS562201', price=0.18, lval='2.2uH'):
        sw, bst, fb, en = f'{name}_SW', f'{name}_BST', f'{name}_FB', 'VCC5V0_SYS_S5'
        lib = 'Regulator_Switching:TPS563200' if part.startswith('TPS5632') else 'Regulator_Switching:TPS562200'
        d.add('U', lib, part, 'Package_TO_SOT_SMD:SOT-23-6',
              {'1': 'GND', '2': sw, '3': 'VCC5V0_SYS_S5', '4': fb, '5': en, '6': bst},
              mpn=f'{part}DDCR', mfr='Texas Instruments', price=price, desc=f'{vout_net} {vout} buck')
        d.C('100nF', bst, sw, desc='bootstrap')
        d.L(lval, sw, vout_net, 'Inductor_SMD:L_Changjiang_FNR4030S', f'FNR4030S{lval.replace(".", "R").replace("uH", "")}MT',
            0.05, mfr='Changjiang')
        d.R(rtop, vout_net, fb)
        d.R(rbot, fb, 'GND')
        d.caps('VCC5V0_SYS_S5', '1x10uF')
        d.caps(vout_net, '2x22uF')

    # Vout = 0.768 * (1 + Rtop/Rbot)
    tps_buck('BUCK_2V0', 'VCC_2V0_PLDO_S3', '2.0V', '16k', '10k')       # 2.00V  PLDO pre-regulator
    tps_buck('BUCK_1V1', 'VCC_1V1_NLDO_S3', '1.1V', '4.3k', '10k')      # 1.098V NLDO pre-regulator
    tps_buck('BUCK_VDD2L', 'VDD2L_DDR_S3', '0.9V', '1.74k', '10k')      # 0.902V LPDDR5 VDD2L
    tps_buck('BUCK_M2', 'VCC3V3_PCIE', '3.3V', '33k', '10k', part='TPS563201', price=0.25, lval='1.5uH')
    # LPDDR5 VDD1 (1.8V) straight from VCC_1V8_S3 through a bead (isolation)
    d.add('FB', 'Device:FerriteBead_Small', '120R@100MHz', 'Inductor_SMD:L_0603_1608Metric',
          {'1': 'VCC_1V8_S3', '2': 'VDD1_DDR_S3'}, mpn='BLM18PG121SN1D', mfr='Murata', price=0.02)
    # S0 load switch for 3.3V IO, enabled by PMIC EXT_EN (sleep control)
    d.add('U', 'Power_Management:AP2171W', 'AP2171W', 'Package_TO_SOT_SMD:SOT-23-5',
          {'1': 'VCC_3V3_S0', '2': 'GND', '3': None, '4': 'PMIC_EXT_EN', '5': 'VCC_3V3_S3'},
          mpn='AP2171WG-7', mfr='Diodes Inc', lcsc='C155555', price=0.12, desc='VCC_3V3_S0 load switch')
    d.caps('VCC_3V3_S0', '1x10uF 1x1uF')
    # M.2 3.3V buck follows VCC_3V3_S0 (EN abs max 7V, Vih 1.6V): SSD powers up
    # only after the PMIC has released the S0 domain.
    for p in d.parts:
        if p.value.startswith('TPS563201'):
            p.nets['5'] = 'VCC_3V3_S0'
    d.notes.append('VDDQ (0.5V) for both SoC DDR PHY and LPDDR5 comes from RK806 BUCK10; '
                   'it is an S0 rail, so DDR self-refresh retention in deep sleep is not supported on rev A.')

    # ===================================================== 04 SoC power
    d.sheet = '04_soc_power'
    pwr_map = [
        (r'CPU_BIG_DVDD_\d+', 'VDD_CPU_BIG_S0'), (r'CPU_LIT_DVDD_\d+', 'VDD_CPU_LIT_S0'),
        (r'GPU_DVDD_\d+', 'VDD_GPU_S0'), (r'NPU_DVDD_\d+', 'VDD_NPU_S0'),
        (r'LOGIC(_MEM)?_DVDD_\d+', 'VDD_LOGIC_S0'),
        (r'DDRPHY_DVDD(_\d+)?', 'VDD_DDR_S0'), (r'DDRPHY_PLL_DVDD', 'VDDA_DDR_PLL_S0'),
        (r'DDRPHY_(CK_|CKE_)?VDDQ(_\d+)?', 'VDDQ_DDR_S0'), (r'DDRPHY_PLL_AVDD1V8', 'VCCA_1V8_S0'),
        (r'PMU_LOGIC_DVDD0V75(_\d+)?', 'VDD_0V75_S3'),
        (r'(PLL_DVDD0V75|OTP_DVDD0V75|USB2_OTG_DVDD0V75|MIPI_DCPHY_AVDD)', 'VDDA_0V75_S0'),
        (r'HDMI_TX_EDP_TX_AVDD[CD]0V75', 'VDDA0V75_HDMI_S0'),
        (r'HDMI_TX_EDP_TX_AVDD(IO|CMN)1V8', 'VCCA1V8_PLDO2_S0'),
        (r'.*AVDD0V85|USB3_OTG0_DP_TX_DVDD0V85', 'VDDA_0V85_S0'),
        (r'MIPI_DCPHY_AVDD1V2', 'VDDA_1V2_S0'),
        (r'(OSC_AVDD1V8|PLL_AVDD1V8|SARADC_AVDD1V8|USB2_OTG_AVDD1V8|.*_AVDD1V8|OSC_UFS_AVDD)', 'VCCA_1V8_S0'),
        (r'USB2_OTG_AVDD3V3', 'VCCA_3V3_S0'),
        (r'PMUIO0_VCC1V8', 'VCC_1V8_S3'), (r'PMUIO1_VCC', 'VCC_3V3_S3'),
        (r'VCCIO0_VCC1V8', 'VCC_1V8_S3'), (r'VCCIO1_VCC', 'VCCIO_SD_S0'),
        (r'VCCIO[236]_VCC', 'VCC_3V3_S0'), (r'VCCIO[45]_VCC(_\d)?', 'VCC_1V8_S3'),
        (r'VCCIO7_VCC', 'VCC_1V8_S3'),
    ]
    from gen_lib import rk3576_pin_class
    for ball, name in SOC_PINS:
        cls = rk3576_pin_class(name)
        if cls == 'GND':
            soc_nets[ball] = 'GND'
        elif cls == 'PWR':
            for rx, net in pwr_map:
                if re.fullmatch(rx, name):
                    soc_nets[ball] = net
                    break
            else:
                raise SystemExit(f'unmapped SoC power pin {ball} {name}')
    # Decoupling at the SoC, sized from Rockchip reference practice
    soc_decaps = {
        'VDD_CPU_BIG_S0': '2x22uF 2x10uF 4x1uF 8x100nF',
        'VDD_CPU_LIT_S0': '1x22uF 1x10uF 2x1uF 5x100nF',
        'VDD_GPU_S0': '1x22uF 1x10uF 2x1uF 5x100nF',
        'VDD_NPU_S0': '1x22uF 1x10uF 2x1uF 5x100nF',
        'VDD_LOGIC_S0': '1x22uF 2x10uF 3x1uF 9x100nF',
        'VDD_DDR_S0': '1x10uF 2x1uF 5x100nF',
        'VDDQ_DDR_S0': '1x10uF 2x1uF 8x100nF',
        'VDD_0V75_S3': '1x1uF 2x100nF', 'VDDA_0V75_S0': '1x1uF 4x100nF',
        'VDDA0V75_HDMI_S0': '1x1uF 2x100nF', 'VCCA1V8_PLDO2_S0': '1x1uF 2x100nF',
        'VDDA_0V85_S0': '1x1uF 6x100nF', 'VDDA_1V2_S0': '1x100nF',
        'VDDA_DDR_PLL_S0': '1x1uF 1x100nF',
        'VCCA_1V8_S0': '1x4.7uF 10x100nF', 'VCCA_3V3_S0': '1x1uF 1x100nF',
        'VCC_1V8_S3': '1x4.7uF 6x100nF', 'VCC_3V3_S3': '1x1uF 1x100nF',
        'VCC_3V3_S0': '1x4.7uF 3x100nF', 'VCCIO_SD_S0': '1x1uF 1x100nF',
    }
    for net, spec in soc_decaps.items():
        d.caps(net, spec)

    # ===================================================== 05 system
    d.sheet = '05_soc_system'
    d.add('Y', 'Device:Crystal_GND24', '24MHz', 'Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm',
          {'1': 'OSC_24M_IN', '2': 'GND', '3': 'OSC_24M_OUT', '4': 'GND'},
          mpn='X322524MOB4SI (24MHz 20pF 10ppm)', mfr='Yangxing', lcsc='C9002', price=0.08)
    d.C('15pF', 'OSC_24M_IN', size='0402', diel='C0G', volt='50V')
    d.C('15pF', 'OSC_24M_OUT', size='0402', diel='C0G', volt='50V')
    d.R('1M', 'OSC_24M_IN', 'OSC_24M_OUT', desc='crystal bias (DNP if not in Rockchip HDG)', dnp=True)
    S('OSC_XIN', 'OSC_24M_IN')
    S('OSC_XOUT', 'OSC_24M_OUT')
    S('NPOR', 'SYS_RESET_L')
    S('PMIC_INT', 'PMIC_INT_L')
    S('I2C1_SCL_M0', 'PMIC_SCL')
    S('I2C1_SDA_M0', 'PMIC_SDA')
    S('PWR_CTRL1', 'PMIC_PWRCTRL1')
    S('PWR_CTRL2', 'PMIC_PWRCTRL2')
    S('PWR_CTRL3', 'PMIC_PWRCTRL3')
    # Boot: SARADC_IN0 high = normal boot, pulled low by MASKROM key = USB download
    S('SARADC_IN0_BOOT', 'SARADC_IN0_BOOT')
    d.R('10k', 'SARADC_IN0_BOOT', 'VCCA_1V8_S0')
    d.C('100nF', 'SARADC_IN0_BOOT')
    sw = dict(lib_id='Switch:SW_Push', fp='Button_Switch_SMD:SW_SPST_PTS810',
              mpn='PTS810 SJM 250 SMTR LFS (alt XKB TS-1088)', mfr='C&K', price=0.06)

    def button(label, net):
        d.add('SW', sw['lib_id'], label, sw['fp'], {'1': net, '2': 'GND'},
              mpn=sw['mpn'], mfr=sw['mfr'], price=sw['price'], desc=f'{label} key')
    button('MASKROM', 'SARADC_IN0_BOOT')
    button('POWER', 'PWRON_L')
    d.R('100R', 'SYS_RESET_L', 'RESET_KEY')
    button('RESET', 'RESET_KEY')
    # Debug UART0 (1500000 8N1, 3.3V PMUIO1 domain) - your USB-TTL plugs in here
    S('UART0_TX_M0', 'DBG_UART_TX')
    S('UART0_RX_M0', 'DBG_UART_RX')
    d.add('J', 'Connector:Conn_01x03_Pin', 'DEBUG UART', 'Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical',
          {'1': 'GND', '2': 'DBG_UART_TX', '3': 'DBG_UART_RX'},
          mpn='2.54mm 1x3 pin header', mfr='generic', price=0.02, desc='1:GND 2:TX(out) 3:RX(in)')
    # Status LED (sinks into GPIO, 3.3V bank)
    S('GPIO0_C5', 'LED_SYS_L')
    d.add('LED', 'Device:LED', 'SYS', 'LED_SMD:LED_0603_1608Metric', {'1': 'LED_SYS_L', '2': 'LED_SYS_A'},
          mpn='19-217/BHC-ZL1M2RY/3T', mfr='Everlight', lcsc='C72041', price=0.01, desc='Blue status LED')
    d.R('1k', 'LED_SYS_A', 'VCC_3V3_S0')
    # DDR ZQ calibration resistors (SoC side)
    S('ZQ_A', 'DDR_ZQ_A')
    S('ZQ_B', 'DDR_ZQ_B')
    d.R('240R', 'DDR_ZQ_A', 'GND', desc='SoC DDR PHY ZQ A')
    d.R('240R', 'DDR_ZQ_B', 'GND', desc='SoC DDR PHY ZQ B')
    S('MIPI_DCPHY_VREG', 'DCPHY_VREG')
    d.C('1uF', 'DCPHY_VREG', desc='DCPHY internal regulator cap')
    # PHY reference resistors: reference design leaves them NC; footprints kept DNP
    for func, net in [('USB2_OTG0_REXT', 'USB2_OTG0_REXT'), ('USB2_OTG1_REXT', 'USB2_OTG1_REXT'),
                      ('USB3_OTG0_REXT', 'USB3_OTG0_REXT'), ('HDMI_TX_REXT', 'HDMI_TX_REXT')]:
        S(func, net)
        d.R('DNP', net, 'GND', dnp=True, desc='PHY REXT (NC per reference)')
    # PMIC-side pull-down on PWRON so the key pulls PWRON_L low
    d.C('100nF', 'PWRON_L', desc='PWRON debounce')

    # ===================================================== 06 LPDDR5
    d.sheet = '06_lpddr5'
    dram = {}
    for ball, name in _read('lpddr5_315b_pins.csv'):
        if name.startswith('VSS'):
            dram[ball] = 'GND'
        elif name.startswith('VDD2H'):
            dram[ball] = 'VDD2H_DDR_S3'
        elif name.startswith('VDD2L'):
            dram[ball] = 'VDD2L_DDR_S3'
        elif name.startswith('VDDQ'):
            dram[ball] = 'VDDQ_DDR_S0'
        elif name.startswith('VDD1'):
            dram[ball] = 'VDD1_DDR_S3'
        elif name.startswith(('NC', 'RFU')):
            continue
        elif name == 'RESET*':
            dram[ball] = 'DDR_RESET_L'
        elif name == 'ZQ_A':
            dram[ball] = 'LP5_ZQ'
        else:
            m = re.fullmatch(r'(DQ\d+|DMI\d|CS\d|CA\d|CK|WCK\d|RDQS\d)(_[TC])?_([AB])', name)
            assert m, name
            sig, tc, ch = m.groups()
            pol = {'_T': 'P', '_C': 'N', None: ''}[tc]
            soc_sig = {'CA': 'A', 'CK': 'CLK'}.get(re.sub(r'\d', '', sig), None)
            if sig.startswith('CA'):
                base = 'A' + sig[2:]
            elif sig == 'CK':
                base = 'CLK'
            elif sig.startswith('CS'):
                base = 'CSN' + sig[2:]
            else:
                base = sig
            dram[ball] = f'LP5_{base}{pol}_{ch}'
    for net in set(v for v in dram.values() if v.startswith('LP5_') and v != 'LP5_ZQ'):
        S(net, net)
    S('LP5_RESET', 'DDR_RESET_L')
    d.add('U', 'sbc:LPDDR5_x32_315b', 'LPDDR5 4GB', 'sbc:LPDDR5_FBGA-315_12.4x15.0mm_P0.8x0.7mm', dram,
          mpn='MT62F1G32D2DS-026 WT:B (4GB) | alt MT62F2G32D4DS-026 WT:B (8GB)', mfr='Micron',
          price=14.50, desc='LPDDR5-6400 x32, 4GB; 8GB is a drop-in BOM option')
    d.R('240R', 'LP5_ZQ', 'VDDQ_DDR_S0', desc='LPDDR5 ZQ (to VDDQ per JEDEC)')
    d.R('10k', 'DDR_RESET_L', 'GND', desc='hold DRAM in reset during power-up')
    d.caps('VDD2H_DDR_S3', '2x10uF 2x1uF 10x100nF')
    d.caps('VDD2L_DDR_S3', '1x10uF 1x1uF 4x100nF')
    d.caps('VDDQ_DDR_S0', '1x10uF 2x1uF 8x100nF')
    d.caps('VDD1_DDR_S3', '1x4.7uF 2x100nF')

    # ===================================================== 07 storage
    d.sheet = '07_storage'
    emmc = {}
    for ball, name in _read('emmc_153b_pins.csv'):
        if name in ('NC', 'RFU'):
            continue
        emmc[ball] = {'VCC': 'VCC_3V3_S0', 'VCCQ': 'VCC_1V8_S3', 'VSS': 'GND', 'VSSQ': 'GND',
                      'VDDI': 'EMMC_VDDI'}.get(name, f'EMMC_{name}')
    d.add('U', 'sbc:eMMC_5.1_153b', 'eMMC 32GB', 'sbc:eMMC_FBGA-153_11.5x13.0mm_P0.5mm', emmc,
          mpn='FEMDNN032G-A3A55 (32GB) | alt KLMBG2JETD-B041 (32GB)', mfr='FORESEE/Samsung',
          price=5.80, desc='eMMC 5.1 HS400, VCCQ=1.8V')
    d.C('1uF', 'EMMC_VDDI', desc='eMMC internal regulator')
    d.caps('VCC_3V3_S0', '1x2.2uF 2x100nF')
    d.caps('VCC_1V8_S3', '1x2.2uF 2x100nF')
    for i in range(8):
        S(f'EMMC_D{i}', f'EMMC_DAT{i}')
    S('EMMC_CMD', 'EMMC_CMD')
    S('EMMC_CLK', 'EMMC_CLK')
    S('EMMC_STRB', 'EMMC_DS')
    S('EMMC_RSTN', 'EMMC_RSTN')
    d.R('10k', 'EMMC_CMD', 'VCC_1V8_S3')
    for i in range(8):
        d.R('10k', f'EMMC_DAT{i}', 'VCC_1V8_S3', size='0201')
    d.R('10k', 'EMMC_DS', 'GND', desc='strobe pull-down')
    # microSD (recovery / alternate boot; your "disposable" card)
    d.add('J', 'Connector:Micro_SD_Card_Det_Hirose_DM3AT', 'microSD', 'Connector_Card:microSD_HC_Hirose_DM3AT-SF-PEJM5',
          {'1': 'SD_D2', '2': 'SD_D3', '3': 'SD_CMD', '4': 'VCC3V3_SD', '5': 'SD_CLK', '6': 'GND',
           '7': 'SD_D0', '8': 'SD_D1', '9': 'SD_DET_L', '10': 'GND', '11': 'GND'},
          mpn='DM3AT-SF-PEJM5', mfr='Hirose', price=0.60, desc='microSD push-push with detect')
    for i in range(4):
        S(f'SDMMC0_D{i}', f'SD_D{i}')
        d.R('10k', f'SD_D{i}', 'VCCIO_SD_S0')
    S('SDMMC0_CMD', 'SD_CMD')
    d.R('10k', 'SD_CMD', 'VCCIO_SD_S0')
    S('SDMMC0_CLK', 'SD_CLK')
    S('SDMMC0_DETN', 'SD_DET_L')
    d.R('100k', 'SD_DET_L', 'VCC_3V3_S3')
    S('SDMMC0_PWREN', 'SD_PWREN')
    d.add('U', 'Power_Management:AP2171W', 'AP2171W', 'Package_TO_SOT_SMD:SOT-23-5',
          {'1': 'VCC3V3_SD', '2': 'GND', '3': None, '4': 'SD_PWREN', '5': 'VCC_3V3_S0'},
          mpn='AP2171WG-7', mfr='Diodes Inc', lcsc='C155555', price=0.12, desc='SD card power switch')
    d.caps('VCC3V3_SD', '1x10uF 1x100nF')

    # ===================================================== 08 NVMe
    d.sheet = '08_nvme'
    from gen_lib import M2_PINS
    m2 = {}
    for n, name in M2_PINS.items():
        m2[str(n)] = {'GND': 'GND', '3V3': 'VCC3V3_PCIE', 'NC': None,
                      'PERp0': 'PCIE0_RXP', 'PERn0': 'PCIE0_RXN',
                      'PETp0': 'M2_PETP0', 'PETn0': 'M2_PETN0',
                      'REFCLKp': 'PCIE0_REFCLKP', 'REFCLKn': 'PCIE0_REFCLKN',
                      'PERST#': 'PCIE0_PERST_L', 'CLKREQ#': 'PCIE0_CLKREQ_L',
                      'PEWAKE#': 'PCIE0_WAKE_L', 'LED1#': 'M2_LED_L', 'PEDET': None,
                      'SUSCLK': None, 'DEVSLP': None, 'SMB_CLK': None, 'SMB_DATA': None,
                      'ALERT#': None}.get(name, None)
    d.add('J', 'sbc:M.2_M_Key', 'M.2 M-KEY', 'sbc:M.2_Socket3_M-Key_H4.2mm', m2,
          mpn='APCI0026-P001A (M.2 M key, H4.2)', mfr='LOTES', price=0.40,
          desc='M.2 2230/2242 NVMe, PCIe2.1 x1 (lane 0 only)')
    # Host TX AC coupling at the connector (device RX); RX caps live on the SSD
    d.C('220nF', 'PCIE0_TXP', 'M2_PETP0', size='0201', desc='PCIe TX AC cap')
    d.C('220nF', 'PCIE0_TXN', 'M2_PETN0', size='0201', desc='PCIe TX AC cap')
    S('PCIE0_TXP', 'PCIE0_TXP')
    S('PCIE0_TXN', 'PCIE0_TXN')
    S('PCIE0_RXP', 'PCIE0_RXP')
    S('PCIE0_RXN', 'PCIE0_RXN')
    S('PCIE0_REFCLKP', 'PCIE0_REFCLKP')
    S('PCIE0_REFCLKN', 'PCIE0_REFCLKN')
    S('GPIO4_C7', 'PCIE0_PERST_L')
    S('PCIE0_CLKREQN_M3', 'PCIE0_CLKREQ_L')
    S('GPIO4_C4', 'PCIE0_WAKE_L')
    d.R('10k', 'PCIE0_CLKREQ_L', 'VCC_3V3_S0')
    d.R('10k', 'PCIE0_WAKE_L', 'VCC_3V3_S0')
    d.R('10k', 'PCIE0_PERST_L', 'GND', desc='hold SSD in reset until driver releases')
    d.caps('VCC3V3_PCIE', '2x22uF 2x100nF')
    d.add('LED', 'Device:LED', 'SSD', 'LED_SMD:LED_0603_1608Metric', {'1': 'M2_LED_L', '2': 'M2_LED_A'},
          mpn='19-217/GHC-YR1S2/3T', mfr='Everlight', lcsc='C72043', price=0.01, desc='SSD activity')
    d.R('1k', 'M2_LED_A', 'VCC3V3_PCIE')
    d.add('H', 'Mechanical:MountingHole_Pad', 'M2 standoff 2242', 'sbc:SMD_Standoff_M2_D4.0mm',
          {'1': 'GND'}, mpn='9774020243R (M2 SMD standoff)', mfr='Wurth', price=0.15,
          desc='M.2 2242 card retention')
    d.add('H', 'Mechanical:MountingHole_Pad', 'M2 standoff 2230', 'sbc:SMD_Standoff_M2_D4.0mm',
          {'1': 'GND'}, mpn='9774020243R (M2 SMD standoff)', mfr='Wurth', price=0.15,
          desc='M.2 2230 card retention')

    # ===================================================== 09 HDMI
    d.sheet = '09_hdmi'
    # RK3576 HDMI2.1 TX: lane3 carries the TMDS clock in TMDS (<=4K60) mode.
    lanes = {'D0': ('HDMI_TX_D0P', 'HDMI_TX_D0N', '7', '9'),
             'D1': ('HDMI_TX_D1P', 'HDMI_TX_D1N', '4', '6'),
             'D2': ('HDMI_TX_D2P', 'HDMI_TX_D2N', '1', '3'),
             'D3': ('HDMI_TX_D3P', 'HDMI_TX_D3N', '10', '12')}
    hdmi = {'2': 'GND', '5': 'GND', '8': 'GND', '11': 'GND', '17': 'GND', 'SH': 'GND',
            '13': 'HDMI_CEC_5V', '14': None, '15': 'HDMI_SCL_5V', '16': 'HDMI_SDA_5V',
            '18': 'VCC5V_HDMI', '19': 'HDMI_HPD_5V'}
    for ln, (p, n, cp, cn) in lanes.items():
        S(p, p)
        S(n, n)
        hdmi[cp], hdmi[cn] = f'HDMI_{ln}P_C', f'HDMI_{ln}N_C'
        d.C('220nF', p, f'HDMI_{ln}P_C', size='0201', desc='TMDS AC coupling')
        d.C('220nF', n, f'HDMI_{ln}N_C', size='0201', desc='TMDS AC coupling')
        # 590R source termination to GND, switched in by HDMI_TX_ON_H
        d.R('590R', f'HDMI_{ln}P_C', f'HDMI_{ln}_TERM')
        d.R('590R', f'HDMI_{ln}N_C', f'HDMI_{ln}_TERM')
        d.add('Q', 'Transistor_FET:BSS138', 'BSS138', 'Package_TO_SOT_SMD:SOT-23',
              {'1': 'HDMI_TX_ON_H', '2': 'GND', '3': f'HDMI_{ln}_TERM'},
              mpn='BSS138', mfr='onsemi/CJ', lcsc='C52895', price=0.01, desc='TMDS termination switch')
    d.add('J', 'Connector:HDMI_A', 'HDMI', 'Connector_Video:HDMI_A_Molex_208658-1001_Horizontal', hdmi,
          mpn='208658-1001', mfr='Molex', price=0.45, desc='HDMI type A, 4K@60 (TMDS) / 4K@120 (FRL)')
    for i, (a, b) in enumerate([('D2', 'D1'), ('D0', 'D3')]):
        d.add('U', 'Power_Protection:TPD4E05U06DQA', 'TPD4E05U06', 'Package_SON:USON-10_2.5x1.0mm_P0.5mm',
              {'1': f'HDMI_{a}P_C', '2': f'HDMI_{a}N_C', '3': 'GND', '4': f'HDMI_{b}P_C',
               '5': f'HDMI_{b}N_C', '8': 'GND', '6': None, '7': None, '9': None, '10': None},
              mpn='TPD4E05U06DQAR', mfr='Texas Instruments', price=0.18, desc='TMDS ESD 0.5pF')
    S('GPIO4_D1', 'HDMI_TX_ON_H')
    # DDC / CEC: BSS138 bidirectional level shifters (3.3V <-> 5V)
    for sig, func in [('SCL', 'HDMI_TX_SCL'), ('SDA', 'HDMI_TX_SDA'), ('CEC', 'HDMI_TX_CEC_M0')]:
        lo = f'HDMI_{sig}'
        S(func, lo)
        d.add('Q', 'Transistor_FET:BSS138', 'BSS138', 'Package_TO_SOT_SMD:SOT-23',
              {'1': 'VCC_3V3_S0', '2': lo, '3': f'HDMI_{sig}_5V'},
              mpn='BSS138', mfr='onsemi/CJ', lcsc='C52895', price=0.01, desc=f'{sig} level shift')
        d.R('4.7k', lo, 'VCC_3V3_S0')
        d.R('1.8k' if sig != 'CEC' else '27k', f'HDMI_{sig}_5V', 'VCC5V_HDMI' if sig != 'CEC' else 'VCC_3V3_S0')
    # HPD 5V -> 3.3V divider
    S('HDMI_TX_HPDIN_M0', 'HDMI_HPD')
    d.R('10k', 'HDMI_HPD_5V', 'HDMI_HPD')
    d.R('20k', 'HDMI_HPD', 'GND')
    d.R('100k', 'HDMI_HPD_5V', 'GND', desc='HPD default low when unplugged')
    # +5V to sink: Schottky + 0.5A PTC (HDMI spec >=55mA, <=0.5A)
    d.add('D', 'Device:D_Schottky', 'B5819W', 'Diode_SMD:D_SOD-123', {'1': 'HDMI_5V_PTC', '2': 'VCC5V0_SYS_S5'},
          mpn='B5819W', mfr='CJ', lcsc='C8598', price=0.01)
    d.add('F', 'Device:Fuse', '0.5A PTC', 'Fuse:Fuse_1206_3216Metric', {'1': 'HDMI_5V_PTC', '2': 'VCC5V_HDMI'},
          mpn='1206L050/15YR', mfr='Littelfuse/BHFUSE', price=0.03)
    d.caps('VCC5V_HDMI', '1x1uF 1x100nF')

    # ===================================================== 10 USB
    d.sheet = '10_usb'
    # OTG0 USB2 on the USB-C power port (device mode: maskrom, fastboot, ADB)
    S('USB2_OTG0_DP', 'USBC_DP')
    S('USB2_OTG0_DM', 'USBC_DM')
    S('USB2_OTG0_VBUSDET', 'USB_OTG0_VBUSDET')
    d.R('56k', 'VBUS_IN', 'USB_OTG0_VBUSDET', desc='VBUS detect divider (5V -> 3.2V)')
    d.R('100k', 'USB_OTG0_VBUSDET', 'GND')
    d.add('U', 'Power_Protection:USBLC6-2SC6', 'USBLC6-2SC6', 'Package_TO_SOT_SMD:SOT-23-6',
          {'1': 'USBC_DP', '6': 'USBC_DP', '3': 'USBC_DM', '4': 'USBC_DM', '2': 'GND', '5': 'VBUS_IN'},
          mpn='USBLC6-2SC6', mfr='ST', lcsc='C7519', price=0.06, desc='USB-C D+/D- ESD')
    # OTG1: USB 3.0 Type-A host
    S('USB2_OTG1_DP', 'USB3A_DP')
    S('USB2_OTG1_DM', 'USB3A_DM')
    S('USB2_OTG1_VBUSDET', 'VBUS_USB3A')     # host: tie VBUSDET to own VBUS
    S('USB3_OTG1_SSTXP', 'USB3_TXP')
    S('USB3_OTG1_SSTXN', 'USB3_TXN')
    S('USB3_OTG1_SSRXP', 'USB3_RXP')
    S('USB3_OTG1_SSRXN', 'USB3_RXN')
    d.C('100nF', 'USB3_TXP', 'USB3A_SSTXP', size='0201', desc='SS TX AC cap')
    d.C('100nF', 'USB3_TXN', 'USB3A_SSTXN', size='0201', desc='SS TX AC cap')
    d.add('J', 'Connector:USB3_A', 'USB3.0 A', 'Connector_USB:USB3_A_Molex_48393-001',
          {'1': 'VBUS_USB3A', '2': 'USB3A_DM', '3': 'USB3A_DP', '4': 'GND',
           '5': 'USB3_RXN', '6': 'USB3_RXP', '7': 'GND', '8': 'USB3A_SSTXN', '9': 'USB3A_SSTXP', '10': 'GND'},
          mpn='48393-0001', mfr='Molex', price=0.45, desc='USB 3.0 type-A host (5Gbps)')
    d.add('U', 'Power_Protection:TPD4E05U06DQA', 'TPD4E05U06', 'Package_SON:USON-10_2.5x1.0mm_P0.5mm',
          {'1': 'USB3_RXP', '2': 'USB3_RXN', '3': 'GND', '4': 'USB3A_SSTXP', '5': 'USB3A_SSTXN', '8': 'GND',
           '6': None, '7': None, '9': None, '10': None},
          mpn='TPD4E05U06DQAR', mfr='Texas Instruments', price=0.18, desc='USB3 SS ESD')
    d.add('U', 'Power_Protection:USBLC6-2SC6', 'USBLC6-2SC6', 'Package_TO_SOT_SMD:SOT-23-6',
          {'1': 'USB3A_DP', '6': 'USB3A_DP', '3': 'USB3A_DM', '4': 'USB3A_DM', '2': 'GND', '5': 'VBUS_USB3A'},
          mpn='USBLC6-2SC6', mfr='ST', lcsc='C7519', price=0.06, desc='USB-A D+/D- ESD')
    d.add('U', 'Power_Management:AP2171W', 'AP2171W', 'Package_TO_SOT_SMD:SOT-23-5',
          {'1': 'VBUS_USB3A', '2': 'GND', '3': 'USB3A_OC_L', '4': 'USB_HOST_PWREN', '5': 'VCC5V0_SYS_S5'},
          mpn='AP2171WG-7 (1.5A limit)', mfr='Diodes Inc', lcsc='C155555', price=0.12,
          desc='USB-A VBUS switch, 900mA USB3 budget')
    S('GPIO0_C4', 'USB_HOST_PWREN')
    S('GPIO0_C6', 'USB3A_OC_L')
    d.R('10k', 'USB3A_OC_L', 'VCC_3V3_S3')
    d.R('100k', 'USB_HOST_PWREN', 'GND')
    d.caps('VBUS_USB3A', '1x47uF/0805 1x100nF')

    # ===================================================== 11 GPIO (SoC GPIO units live here)
    d.sheet = '11_soc_gpio'
    d.notes.append('All RK3576 pins not listed in design.py are left unconnected (no-connect flags). '
                   'A 40-pin expansion header and Ethernet are deliberate omissions for cost; '
                   'the GPIO sheet shows every free ball if you want to add them.')

    # ===================================================== 12 mechanical
    d.sheet = '12_mechanical'
    for i in range(4):
        d.add('H', 'Mechanical:MountingHole_Pad', 'M2.5', 'MountingHole:MountingHole_2.7mm_M2.5_Pad_Via',
              {'1': 'GND'}, price=0.0, desc='board mounting hole', bom=False)
    for i in range(3):
        d.add('FID', 'Mechanical:Fiducial', 'FID', 'Fiducial:Fiducial_1mm_Mask2mm', {}, price=0.0, bom=False)

    # ===================================================== SoC part (units spread over sheets)
    d.sheet = '04_soc_power'
    from gen_lib import rk3576_units
    unit_sheet = {}
    for ui, (lbl, _l, _r) in enumerate(rk3576_units(), 1):
        unit_sheet[ui] = {'DDR': '06_lpddr5', 'SYS': '05_soc_system', 'PWR': '04_soc_power',
                          'GND': '04_soc_power'}.get(lbl, '11_soc_gpio')
    d.add('U', 'sbc:RK3576', 'RK3576', 'sbc:RK3576_FCCSP-698_16.1x17.2mm_PLACEHOLDER',
          {b: soc_nets.get(b) for b, _ in SOC_PINS}, mpn='RK3576', mfr='Rockchip', price=22.00,
          desc='Octa-core 4xA72@2.2GHz + 4xA53, Mali-G52, 6 TOPS NPU', unit_sheets=unit_sheet, ref='U401')
    refs = [p.ref for p in d.parts]
    dup = {r for r in refs if refs.count(r) > 1}
    assert not dup, f'duplicate references: {sorted(dup)}'
    return d


if __name__ == '__main__':
    d = build()
    nets = {}
    for p in d.parts:
        for pin, n in p.nets.items():
            if n:
                nets.setdefault(n, []).append(f'{p.ref}.{pin}')
    single = sorted(n for n, v in nets.items() if len(v) == 1)
    print(f'{len(d.parts)} parts, {len(nets)} nets')
    print('single-pin nets:', single)

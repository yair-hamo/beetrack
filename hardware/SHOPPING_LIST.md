# Shopping list

**Now: the cages, rack and stand** (section 1). The camera, light and box come later (section 2, unchanged
from the first plan, not needed yet). The design is in [README.md](README.md); printable parts are in
[`cages/stl/`](cages/stl/).

How to read the links:
- **Product** links point to one specific product.
- **Search** links open an AliExpress or Amazon search with the right words. Pick a listing that matches the
  *Must have* column, preferably with many orders and good reviews. Listings change too often to pin one.

Prices are rough (November 2026), in shekels, and should be checked when ordering.

# 1. Now: 4 cages, rack and stand (≈ ₪400–700)

| # | Item | Qty | Must have | Link | ≈ ₪ |
|---|---|---|---|---|---|
| N1 | **PETG filament, white** | 2 kg | PETG, not PLA (PLA softens in a warm bee room). All parts together use about 1 kg; the rest is for test prints and spares. | [Bambu PETG HF](https://bambulab.com/en/filament/petg-hf) | 200–300 |
| N2 | **Glass, 2 mm, cut to 104.0 × 99.0 mm**, edges ground ("seamed") | 8 (4 + spares) | Clear float glass, from a local glazier. **Order after printing one test cage**, and measure the real thickness: if it isn't 2.0 mm, change `GLASS_T` and reprint. Perspex: only *cast* acrylic (see README). | Local glazier | 40–120 |
| N3 | Neodymium magnet discs **10 × 2 mm** | 20 (16 + spares) | N35 or stronger. 2 in each cage, 2 in each rack pocket. | [Search](https://www.aliexpress.com/w/wholesale-neodymium-magnet-10x2mm.html) | 15–30 |
| N4 | **M5 × 12 countersunk screws** + **M5 hex nuts** | 2 + 2 (a small pack) | Countersunk (flat head, 90°), to fix the rack to the stand. | [Search](https://www.aliexpress.com/w/wholesale-M5-countersunk-screw-kit-nuts.html) | 10–20 |
| N5 | Stick-on **rubber feet, Ø 10 mm** | 4 | So the stand doesn't slide on the table. | [Search](https://www.aliexpress.com/w/wholesale-rubber-feet-10mm-self-adhesive.html) | 5–15 |
| N6 | Optional: **2020 aluminium profile**, about 60 cm, + 2 M5 drop-in T-nuts and M5 × 10 screws | 1 | Only to fix the stand (and later the camera) on one rail at a fixed distance. 20 × 20 mm, 6 mm slot. | [Search](https://www.aliexpress.com/w/wholesale-2020-aluminum-profile-cut-to-length.html) | 30–60 |
| N7 | Feeders: 1.5 mL microtubes, cut syringes, cotton dental rolls | — | Lab stock. They must fit the **Ø 9 mm** holes; if your tubes need a different hole, change `FEED_D` in `cages.py`. | Lab stock | — |
| N8 | Queen-cell holders (the blue cups) | 12 | You have these. Measure the **disc diameter** and the tube diameter before printing (`QC_FLANGE_D`, `QC_D`). | Lab stock | — |
| N9 | **Posca PC-1M** (fine tip) paint markers: **fluorescent set** + standard colours | 1 set each | For marking the bees. Water-based opaque paint; fine tip for 2–3 mm dots. | [Search (Amazon)](https://www.amazon.com/s?k=posca+pc-1m+fluorescent) | 60–150 |
| N10 | Queen-marking tube with plunger (holds a worker while you paint) | 2 | Soft mesh or sponge plunger. | [Search](https://www.aliexpress.com/w/wholesale-queen-bee-marking-tube-plunger.html) | 15–30 |

## Before you order the glass

1. Print **one** cage, one foundation and one cap.
2. Check the queen-cell holder, a feeder tube and the cap in their holes.
3. Measure the glass you'll use, fix the numbers in `cages.py` if needed, run `python hardware/cages/cages.py check`,
   then order the glass and print the rest.

# 2. Later: camera, light and box (not needed yet)

## A. Camera and optics

| # | Item | Qty | Must have | Link | ≈ ₪ |
|---|---|---|---|---|---|
| A1 | **Hikrobot MV-CS050-10UC** (colour, USB3, 5 MP, Sony IMX264, global shutter) | 1 | The **10UC** variant (colour + USB). Ask the seller: is a USB3 cable included? Is a lens included (usually not)? | [Product (your listing)](https://he.aliexpress.com/item/1005011936471983.html) | 1,040 |
| A2 | **Lens 12 mm, C-mount**, for 2/3" sensors, ≥ 5 MP | 1 | **C-mount**; **2/3" or larger** image circle; **≥ 5 MP**; **manual focus and manual iris with locking screws**; *not* CS-mount, *not* varifocal. Note its filter thread size. | [Search](https://www.aliexpress.com/w/wholesale-12mm-c-mount-lens-5mp-2%2F3.html) · Hikrobot's own: [search MVL-HF1228M-6MP](https://www.aliexpress.com/w/wholesale-MVL-HF1228M-6MP.html) · Premium reference: [Computar M1224-MPW2](https://avsupply.com/ITM/34183/M1224-MPW2.html) | 250–450 |
| A3 | USB 3.0 cable, **Micro-B with screw lock** → USB-A, **3 m** | 1 | Screw lock on the camera end. Skip if included with A1. | [Search](https://www.aliexpress.com/w/wholesale-usb3.0-micro-b-screw-lock-cable-industrial-camera.html) | 40–80 |
| A4 | **Linear polariser film**, A4 sheet | 2 | *Linear* (not circular), adhesive-free or with protective film. One sheet goes over the light panel, a disc from the other goes in front of the lens. | [Search](https://www.aliexpress.com/w/wholesale-linear-polarizer-film-sheet-A4.html) | 30–60 |

## B. Light (constant, inside the box)

| # | Item | Qty | Must have | Link | ≈ ₪ |
|---|---|---|---|---|---|
| B1 | **COB LED strip, 24 V, CRI ≥ 90** (Ra 90+ or 95), **4000 K** neutral white, 5 m | 1 | **24 V**, **CRI ≥ 90** (true colours), COB (no dots). | [Search](https://www.aliexpress.com/w/wholesale-COB-LED-strip-24V-CRI90-4000K.html) | 60–120 |
| B2 | **24 V DC plug-in power adapter, 3 A**, with a DC barrel plug | 1 | A closed plug-in adapter (safer in a lab than open mains wiring). | [Search](https://www.aliexpress.com/w/wholesale-24V-3A-power-adapter-5.5x2.1.html) | 40–70 |
| B3 | DC barrel female connector with screw terminals (5.5 × 2.1 mm) + 2-pin connectors for COB strips | 1 pack each | Matches B2's plug; COB strip connectors of the strip's width (usually 8 or 10 mm). | [Search](https://www.aliexpress.com/w/wholesale-DC-female-connector-5.5x2.1-screw-terminal.html) · [Search](https://www.aliexpress.com/w/wholesale-COB-LED-strip-connector-2-pin.html) | 15–30 |
| B4 | **Opal (milky white) acrylic, 3 mm**, 300 × 300 mm, with a **Ø 60 mm hole in the centre** | 1 | Opal/"milky" diffuser acrylic, not clear. A local plastics or laser-cutting shop can cut the hole; otherwise buy a sheet and drill. | [Search](https://www.aliexpress.com/w/wholesale-opal-acrylic-sheet-3mm-diffuser.html) | 40–80 |

No dimmer: the light runs at full, constant power so it is identical in every run and doesn't flicker.

## C. Frame and box

| # | Item | Qty | Must have | Link | ≈ ₪ |
|---|---|---|---|---|---|
| C1 | **2020 aluminium profile, cut to length**: **4 × 600 mm** + **9 × 300 mm** | 13 pcs | 20 × 20 mm, 6 mm slot ("2020"), cut square. A local aluminium-profile supplier also works. | [Search](https://www.aliexpress.com/w/wholesale-2020-aluminum-profile-cut-to-length.html) | 150–250 |
| C2 | 2020 inner corner brackets with screws | 24 | For 2020 / 6 mm slot. | [Search](https://www.aliexpress.com/w/wholesale-2020-inner-corner-bracket.html) | 30–60 |
| C3 | M5 drop-in T-nuts + M5 × 8 and M5 × 10 screws | 50 + 50 | For 2020 / 6 mm slot. | [Search](https://www.aliexpress.com/w/wholesale-2020-M5-T-nut-screw-kit.html) | 30–50 |
| C4 | **Black PVC foam board (Forex) 3 mm**: 4 × 600 × 340 mm (sides, top, bottom) + 1 × 340 × 340 mm (front) + LED board 300 × 300 mm with Ø 60 mm hole | 6 pcs | Matte black. A local sign/plastics shop cuts it to size. | Local sign shop | 100–200 |
| C5 | **Back panel**: black PVC or plywood **6 mm**, 340 × 340 mm | 1 | Holes to be set when the box is redesigned around the new rack. | Local / cut yourself | 30–60 |
| C6 | Neodymium magnet discs **10 × 2 mm** (plates ↔ rack) and **10 × 3 mm** (side door) | 30 + 10 | N35 or stronger. | [Search](https://www.aliexpress.com/w/wholesale-neodymium-magnet-10x2mm.html) | 20–40 |

## F. Calibration and monitoring

| # | Item | Qty | Must have | Link | ≈ ₪ |
|---|---|---|---|---|---|
| F1 | Small **24-patch colour checker** card | 1 | Stays in view in a corner of the rack, so every recording can be colour-checked. | [Search](https://www.aliexpress.com/w/wholesale-color-checker-24-patch-card.html) | 30–100 |
| F2 | **Temperature + humidity logger** (e.g. Govee H5075, Inkbird IBS-TH2) | 2 | Logs to the phone. One inside the box next to the plates, one in the room. | [Search (Amazon)](https://www.amazon.com/s?k=govee+h5075+thermometer+hygrometer) | 50–100 each |
| F3 | Lux meter (optional, to report the light level in the methods) | 1 | Any cheap digital lux meter. | [Search](https://www.aliexpress.com/w/wholesale-digital-lux-meter.html) | 40–80 |

## G. Computer and storage

| # | Item | Qty | Must have | Link | ≈ ₪ |
|---|---|---|---|---|---|
| G1 | The lab PC or a laptop you already have | 1 | ≥ 4 cores, 16 GB RAM, a **USB 3.0 port on the computer itself** (not a hub), Windows 10/11 or Linux. | — | — |
| G2 | **External hard disk 4 TB** (USB 3) | 1 | For recordings: a 48 h run of 4 plates is roughly 250–500 GB (to be measured in the pilot). | [Search (Amazon)](https://www.amazon.com/s?k=external+hard+drive+4TB) | 350–450 |
| G3 | Small UPS 600–850 VA (optional for the pilot) | 1 | So a power blip doesn't end a 48 h run. | [Search (Amazon)](https://www.amazon.com/s?k=ups+850va) | 350–500 |

Pilot camera + light + box ≈ ₪2,300–3,500, about half of it the camera and lens. The box frame (C) and its
panels will be redesigned when the camera stage starts; only the camera (A) and light (B) choices stand.

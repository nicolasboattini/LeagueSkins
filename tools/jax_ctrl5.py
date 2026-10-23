import sys, zipfile, json, struct
sys.path.insert(0, __import__('os').path.dirname(__file__))
import binlib as B
from retarget import read_wad, write_wad, xx
B.load_names()
S = sys.argv[1] if len(sys.argv) > 1 else './'
f = B.fnv
def H(n): return ('p', 17, struct.pack('<I', f(n) if isinstance(n, str) else n))
def HL(names): return ('l', 0x80, 17, [H(n) for n in names])
def U32(v): return ('p', 7, struct.pack('<I', v))

z = zipfile.ZipFile(S + 'src/jax_ruby.fantome')
hdr, ents = read_wad(z.read('WAD/Jax.wad.client'))
ANIM = xx('data/characters/jax/animations/skin0.bin')
ab = [e for e in ents if e[0] == ANIM][0]
b = B.Bin(ab[1]); assert b.dumps() == ab[1]
g = b.entries[0][2]
cm = B.get(g, 'mClipDataMap')[2]; mm = B.get(g, 'mMaskDataMap')[2]; tm = B.get(g, 'mTrackDataMap')[2]
clips = {B.u32(k): v for k, v in cm[3]}
assert f('Toggle') not in clips
# anim file of a looping clip, like builder used Channel_Loop
chan = clips[f('Channel')]
animres = B.get(chan[3], 'mAnimationResourceData')
# zero mask with joint count of existing masks
nj = len(B.get(mm[3][0][1][3], 'mWeightList')[2][3])
mask = ('o', 0x83, f('MaskData'), [[f('mWeightList'), 0x80, ('l', 0x80, 10, [('p', 10, b'\0\0\0\0')] * nj)]])
mm[3].append((H('CtrlCycleNullMask'), mask))
tm[3].append((H('Toggle'), ('o', 0x83, f('TrackData'), [])))

def sved(field, names):
    return ('o', 0x82, f('SubmeshVisibilityEventData'), [[f(field), 0x80, HL(names)]])
def atomic(show, hide):
    return ('o', 0x82, f('AtomicClipData'), [
        [f('mFlags'), 7, U32(14)],
        [f('mTrackDataName'), 17, H('Toggle')],
        [f('mMaskDataName'), 17, H('CtrlCycleNullMask')],
        [f('mEventDataMap'), 0x86, ('m', 17, 0x82, [(H('Show'), sved('mShowSubmeshList', show)), (H('Hide'), sved('mHideSubmeshList', hide))])],
        animres])
def parallel(clip):
    return ('o', 0x82, f('ParallelClipData'), [[f('mFlags'), 7, U32(14)], [f('mClipNameList'), 0x80, HL([clip])]])
cond = ('o', 0x82, f('ConditionBoolClipData'), [
    [f('Updater'), 0x82, ('o', 0x82, f('LogicDriverBoolParametricUpdater'), [
        [f('driver'), 0x82, ('o', 0x82, f('SubmeshVisibilityBoolDriver'), [
            [f('Submeshes'), 0x80, HL(['Wings'])], [f('VISIBLE'), 1, ('p', 1, b'\x01')]])]])],
    [f('mTrueConditionClipName'), 17, H('ctrlwings_par_off')],
    [f('mFalseConditionClipName'), 17, H('ctrlwings_par_on')]])
cm[3].extend([
    (H('Toggle'), cond),
    (H('ctrlwings_par_off'), parallel('ctrlwings_set_off')),
    (H('ctrlwings_set_off'), atomic(['Engine'], ['Wings', 'Engine_Level6'])),
    (H('ctrlwings_par_on'), parallel('ctrlwings_set_on')),
    (H('ctrlwings_set_on'), atomic(['Wings', 'Engine_Level6'], ['Engine'])),
])
nd = b.dumps(); assert B.Bin(nd).dumps() == nd
ab[1] = nd
out = S + 'out/jax_mk_ruby_ctrl5_skin0.fantome'
with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as zo:
    zo.writestr('META/info.json', json.dumps({"Name": "Mecha Kingdoms Jax (Ruby) - Ctrl+5 alas", "Author": "Sunshine Builder + Ctrl+5 wings toggle",
        "Version": "2.3.0-ctrl5", "Description": "Ctrl+5 alterna alas (Wings + Engine_Level6) / motor base (Engine)."}, indent=2))
    zo.writestr('WAD/Jax.wad.client', write_wad(hdr, ents), compress_type=zipfile.ZIP_STORED)
print('ok', nj, out)

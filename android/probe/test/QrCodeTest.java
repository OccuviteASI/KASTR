package app.kastr.probe;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Random;

/**
 * Desktop-JVM check of QrCode (no Android, no libraries). build.sh runs it before packaging.
 * 1. Known vectors from the public standard / tutorials: Reed-Solomon of the "HELLO WORLD" 1-M example, format strings,
 *    version-7 info, data capacities, alignment positions.
 * 2. A reader written here independently of the encoder: rebuilds the function-module map from the standard's tables,
 *    reads the format bits back, unmasks, walks the zig-zag, de-interleaves, checks every block's Reed-Solomon syndromes
 *    are zero, parses the byte-mode segment and compares it with what went in.
 */
public final class QrCodeTest {

    private static int failures = 0;

    private static void check(boolean ok, String what) {
        if (!ok) {
            failures++;
            System.out.println("FAIL " + what);
        }
    }

    public static void main(String[] args) {
        knownVectors();
        Random rnd = new Random(2192);
        int decoded = 0;
        for (char lvl : QrCode.LEVELS) {
            for (int len : new int[] {0, 1, 7, 17, 32, 60, 100, 150, 230, 321, 400, 520, 700}) {
                byte[] msg = new byte[len];
                rnd.nextBytes(msg);
                QrCode q;
                try {
                    q = QrCode.encodeBytes(msg, lvl);
                } catch (IllegalArgumentException e) {
                    continue;
                }
                if (q.version > 20) continue;   // the reader's alignment table covers 1..20
                byte[] back = readBack(q);
                check(back != null && Arrays.equals(back, msg), "round trip level " + lvl + " len " + len + " v" + q.version);
                decoded++;
            }
        }
        String sample = "{\"p\":\"0.21.92\",\"t\":\"2026-10-28 12:00\",\"mf\":\"Yealink\",\"md\":\"MeetingBar A50\",\"a\":\"12/31\"}";
        byte[] sb = sample.getBytes(StandardCharsets.UTF_8);
        byte[] back = readBack(QrCode.encodeBytes(sb, 'M'));
        check(back != null && Arrays.equals(back, sb), "sample report round trip");
        check(decoded >= 30, "enough round trips ran (" + decoded + ")");
        // too long must throw
        boolean threw = false;
        try {
            QrCode.encodeBytes(new byte[2954], 'L');
        } catch (IllegalArgumentException e) {
            threw = true;
        }
        check(threw, "2954 bytes is too long even at 40-L");
        QrCode big = QrCode.encodeBytes(new byte[2953], 'L');
        check(big.version == 40 && big.size == 177, "2953 bytes fits 40-L");
        System.out.println(failures == 0 ? "QrCodeTest OK (" + decoded + " round trips)" : "QrCodeTest FAILED: " + failures);
        if (failures != 0) System.exit(1);
    }

    private static void knownVectors() {
        // "HELLO WORLD" 1-M data codewords and their 10 EC codewords (widely published worked example)
        int[] data = {32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17};
        int[] ecc = {196, 35, 39, 119, 235, 215, 231, 226, 93, 23};
        byte[] d = new byte[data.length];
        for (int i = 0; i < d.length; i++) d[i] = (byte) data[i];
        byte[] got = QrCode.reedSolomonRemainder(d, QrCode.reedSolomonDivisor(10));
        boolean same = got.length == ecc.length;
        for (int i = 0; same && i < ecc.length; i++) same = (got[i] & 0xFF) == ecc[i];
        check(same, "Reed-Solomon HELLO WORLD 1-M");
        // format strings from the standard's table
        check(QrCode.formatBits('L', 0) == 0b111011111000100, "format L/0");
        check(QrCode.formatBits('M', 0) == 0b101010000010010, "format M/0");
        check(QrCode.formatBits('Q', 0) == 0b011010101011111, "format Q/0");
        check(QrCode.formatBits('H', 0) == 0b001011010001001, "format H/0");
        check(QrCode.formatBits('L', 4) == 0b110011000101111, "format L/4");
        check(QrCode.formatBits('M', 7) == 0b100101010100000, "format M/7");
        check(QrCode.versionBits(7) == 0x07C94, "version 7 info");
        check(QrCode.versionBits(40) == 0x28C69, "version 40 info");
        // data codeword capacities (standard table)
        int[][] cap = {{1, 0, 19}, {1, 1, 16}, {1, 2, 13}, {1, 3, 9}, {5, 2, 62}, {6, 0, 136}, {7, 1, 124}, {10, 1, 216},
            {15, 0, 523}, {20, 1, 669}, {40, 0, 2956}, {40, 1, 2334}, {40, 2, 1666}, {40, 3, 1276}};
        for (int[] c : cap) check(QrCode.numDataCodewords(c[0], c[1]) == c[2], "capacity v" + c[0] + " level " + c[1]);
        for (int v = 1; v <= 20; v++) check(Arrays.equals(QrCode.alignmentPositions(v), ALIGN[v]), "alignment v" + v);
        check(Arrays.equals(QrCode.alignmentPositions(32), new int[] {6, 34, 60, 86, 112, 138}), "alignment v32");
        check(Arrays.equals(QrCode.alignmentPositions(40), new int[] {6, 30, 58, 86, 114, 142, 170}), "alignment v40");
    }

    // ---- independent reader ----
    private static final int[][] ALIGN = {
        null, {}, {6, 18}, {6, 22}, {6, 26}, {6, 30}, {6, 34}, {6, 22, 38}, {6, 24, 42}, {6, 26, 46}, {6, 28, 50},
        {6, 30, 54}, {6, 32, 58}, {6, 34, 62}, {6, 26, 46, 66}, {6, 26, 48, 70}, {6, 26, 50, 74}, {6, 30, 54, 78},
        {6, 30, 56, 82}, {6, 30, 58, 86}, {6, 34, 62, 90},
    };

    private static byte[] readBack(QrCode q) {
        int n = q.size;
        int ver = (n - 17) / 4;
        boolean[][] fn = new boolean[n][n];
        // finders + separators + format areas
        for (int y = 0; y < 9; y++) for (int x = 0; x < 9; x++) fn[y][x] = true;
        for (int y = 0; y < 9; y++) for (int x = n - 8; x < n; x++) fn[y][x] = true;
        for (int y = n - 8; y < n; y++) for (int x = 0; x < 9; x++) fn[y][x] = true;
        for (int i = 0; i < n; i++) {
            fn[6][i] = true;
            fn[i][6] = true;
        }
        int[] al = ALIGN[ver];
        for (int a : al) for (int b : al) {
            if ((a == 6 && b == 6) || (a == 6 && b == al[al.length - 1]) || (a == al[al.length - 1] && b == 6)) continue;
            for (int dy = -2; dy <= 2; dy++) for (int dx = -2; dx <= 2; dx++) fn[b + dy][a + dx] = true;
        }
        if (ver >= 7) {
            for (int i = 0; i < 6; i++) for (int j = n - 11; j < n - 8; j++) {
                fn[i][j] = true;
                fn[j][i] = true;
            }
        }
        // the encoder must agree on which modules are function modules
        for (int y = 0; y < n; y++) for (int x = 0; x < n; x++)
            if (fn[y][x] != q.isFunctionModule(x, y)) {
                check(false, "function map differs at " + x + "," + y + " v" + ver);
                return null;
            }
        // format bits (copy 1), bit 14 first: (8,0..5),(8,7),(8,8),(7,8),(5..0,8)
        int fmt = 0;
        int[][] fpos = {{8, 0}, {8, 1}, {8, 2}, {8, 3}, {8, 4}, {8, 5}, {8, 7}, {8, 8}, {7, 8}, {5, 8}, {4, 8}, {3, 8}, {2, 8}, {1, 8}, {0, 8}};
        for (int i = 0; i < 15; i++) if (q.get(fpos[i][0], fpos[i][1])) fmt |= 1 << i;
        int fmt2 = 0;
        for (int i = 0; i < 8; i++) if (q.get(n - 1 - i, 8)) fmt2 |= 1 << i;
        for (int i = 8; i < 15; i++) if (q.get(8, n - 15 + i)) fmt2 |= 1 << i;
        check(fmt == fmt2, "format copies agree");
        check(q.get(8, n - 8), "dark module");
        int raw = fmt ^ 0x5412;
        int lvlBits = raw >>> 13;
        int msk = (raw >>> 10) & 7;
        char lvl = "MLHQ".charAt(lvlBits);
        check(lvl == q.ecl && msk == q.mask, "format decodes to level/mask");
        // BCH check on format
        int rem = raw;
        for (int i = 14; i >= 10; i--) if (((rem >>> i) & 1) != 0) rem ^= 0x537 << (i - 10);
        check(rem == 0, "format BCH remainder");
        // finder pattern centres dark, ring light
        check(q.get(3, 3) && !q.get(1, 3) && q.get(0, 3) && q.get(n - 4, 3) && q.get(3, n - 4), "finder patterns");
        // read codeword bits in zig-zag order, unmasked
        int total = 0;
        for (int y = 0; y < n; y++) for (int x = 0; x < n; x++) if (!fn[y][x]) total++;
        byte[] cw = new byte[total / 8];
        int bitIdx = 0;
        int col = n - 1;
        boolean up = true;
        while (col > 0) {
            if (col == 6) col--;
            for (int k = 0; k < n; k++) {
                int y = up ? n - 1 - k : k;
                for (int x = col; x >= col - 1; x--) {
                    if (fn[y][x]) continue;
                    boolean b = q.get(x, y) ^ QrCode.maskBit(msk, x, y);
                    if (bitIdx / 8 < cw.length && b) cw[bitIdx / 8] |= (byte) (0x80 >>> (bitIdx % 8));
                    bitIdx++;
                }
            }
            up = !up;
            col -= 2;
        }
        int li = QrCode.levelIndex(lvl);
        int blocks = QrCode.NUM_ERROR_CORRECTION_BLOCKS[li][ver];
        int eccLen = QrCode.ECC_CODEWORDS_PER_BLOCK[li][ver];
        int nShort = blocks - cw.length % blocks;
        int shortLen = cw.length / blocks;
        byte[][] blk = new byte[blocks][];
        for (int j = 0; j < blocks; j++) blk[j] = new byte[shortLen + (j < nShort ? 0 : 1)];
        int k = 0;
        int dataShort = shortLen - eccLen;
        for (int i = 0; i < dataShort + 1; i++)
            for (int j = 0; j < blocks; j++) {
                if (i == dataShort && j < nShort) continue;
                blk[j][i] = cw[k++];
            }
        for (int i = 0; i < eccLen; i++)
            for (int j = 0; j < blocks; j++) blk[j][blk[j].length - eccLen + i] = cw[k++];
        check(k == cw.length, "all codewords consumed");
        java.io.ByteArrayOutputStream data = new java.io.ByteArrayOutputStream();
        for (int j = 0; j < blocks; j++) {
            for (int r = 0; r < eccLen; r++) {
                // syndrome S_r = C(alpha^r), Horner with the first codeword as the highest power
                int s = 0;
                int a = pow2(r);
                for (byte b : blk[j]) s = QrCode.gfMul(s, a) ^ (b & 0xFF);
                if (s != 0) {
                    check(false, "Reed-Solomon syndrome block " + j + " v" + ver);
                    return null;
                }
            }
            data.write(blk[j], 0, blk[j].length - eccLen);
        }
        byte[] d = data.toByteArray();
        // parse: mode 0100, count (8 or 16 bits), bytes
        int[] pos = {0};
        int mode = bits(d, pos, 4);
        if (mode == 0) return new byte[0];
        check(mode == 4, "byte mode indicator");
        int count = bits(d, pos, ver < 10 ? 8 : 16);
        byte[] out = new byte[count];
        for (int i = 0; i < count; i++) out[i] = (byte) bits(d, pos, 8);
        return out;
    }

    private static int pow2(int r) {
        int a = 1;
        for (int i = 0; i < r; i++) a = QrCode.gfMul(a, 2);
        return a;
    }

    private static int bits(byte[] d, int[] pos, int n) {
        int v = 0;
        for (int i = 0; i < n; i++, pos[0]++) v = (v << 1) | ((d[pos[0] / 8] >>> (7 - pos[0] % 8)) & 1);
        return v;
    }
}

package app.kastr.probe;

import java.util.Arrays;

/**
 * A small QR Code encoder (byte mode only, ISO/IEC 18004 model 2, versions 1..40), written for the KASTR probe so the app
 * needs no library. Plain Java with no Android classes, so tests run it on a desktop JVM (android/probe/test/QrCodeTest).
 * The layout follows the public standard: function patterns, Reed-Solomon over GF(256)/0x11D, block interleaving, zig-zag
 * placement, the eight masks scored by the four penalty rules, BCH format and version bits.
 */
public final class QrCode {

    public static final char[] LEVELS = {'L', 'M', 'Q', 'H'};

    public final int version;
    public final int size;
    public final char ecl;
    public final int mask;

    private final boolean[][] modules;   // [y][x], true = dark
    private final boolean[][] isFunction;

    /** Encodes the bytes at the given level ('L','M','Q','H') in the smallest version that fits; throws when too long. */
    public static QrCode encodeBytes(byte[] data, char ecl) {
        int li = levelIndex(ecl);
        for (int ver = 1; ver <= 40; ver++) {
            int ccBits = ver < 10 ? 8 : 16;
            if (data.length >= (1 << ccBits)) continue;
            int capBits = numDataCodewords(ver, li) * 8;
            int used = 4 + ccBits + data.length * 8;
            if (used > capBits) continue;
            BitBuf bb = new BitBuf();
            bb.append(0x4, 4);
            bb.append(data.length, ccBits);
            for (byte b : data) bb.append(b & 0xFF, 8);
            bb.append(0, Math.min(4, capBits - bb.len));
            bb.append(0, (8 - bb.len % 8) % 8);
            for (int pad = 0xEC; bb.len < capBits; pad ^= 0xEC ^ 0x11) bb.append(pad, 8);
            return new QrCode(ver, ecl, bb.toBytes());
        }
        throw new IllegalArgumentException("data too long for a QR code: " + data.length + " bytes");
    }

    private QrCode(int ver, char ecl, byte[] dataCodewords) {
        this.version = ver;
        this.ecl = ecl;
        this.size = ver * 4 + 17;
        modules = new boolean[size][size];
        isFunction = new boolean[size][size];
        drawFunctionPatterns();
        byte[] all = addEccAndInterleave(dataCodewords);
        drawCodewords(all);
        int best = 0;
        long minPenalty = Long.MAX_VALUE;
        for (int m = 0; m < 8; m++) {
            applyMask(m);
            drawFormatBits(m);
            long p = penaltyScore();
            if (p < minPenalty) {
                best = m;
                minPenalty = p;
            }
            applyMask(m);   // XOR again undoes it
        }
        mask = best;
        applyMask(best);
        drawFormatBits(best);
    }

    public boolean get(int x, int y) {
        return x >= 0 && x < size && y >= 0 && y < size && modules[y][x];
    }

    public boolean isFunctionModule(int x, int y) {
        return isFunction[y][x];
    }

    // ---- tables (index 0 unused; rows L, M, Q, H) ----
    static final int[][] ECC_CODEWORDS_PER_BLOCK = {
        {-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30},
        {-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28},
        {-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30},
        {-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30},
    };
    static final int[][] NUM_ERROR_CORRECTION_BLOCKS = {
        {-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25},
        {-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49},
        {-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68},
        {-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81},
    };
    /** Format-info bits for L, M, Q, H. */
    private static final int[] FORMAT_BITS = {1, 0, 3, 2};

    static int levelIndex(char ecl) {
        switch (ecl) {
            case 'L': return 0;
            case 'M': return 1;
            case 'Q': return 2;
            case 'H': return 3;
            default: throw new IllegalArgumentException("level must be L, M, Q or H");
        }
    }

    static int numRawDataModules(int ver) {
        int result = (16 * ver + 128) * ver + 64;
        if (ver >= 2) {
            int numAlign = ver / 7 + 2;
            result -= (25 * numAlign - 10) * numAlign - 55;
            if (ver >= 7) result -= 36;
        }
        return result;
    }

    static int numDataCodewords(int ver, int li) {
        return numRawDataModules(ver) / 8 - ECC_CODEWORDS_PER_BLOCK[li][ver] * NUM_ERROR_CORRECTION_BLOCKS[li][ver];
    }

    static int[] alignmentPositions(int ver) {
        if (ver == 1) return new int[0];
        int numAlign = ver / 7 + 2;
        int step = (ver * 8 + numAlign * 3 + 5) / (numAlign * 4 - 4) * 2;
        int[] result = new int[numAlign];
        result[0] = 6;
        for (int i = result.length - 1, pos = ver * 4 + 17 - 7; i >= 1; i--, pos -= step) result[i] = pos;
        return result;
    }

    /** The 15 format bits (after the 0x5412 XOR) for a level and mask. */
    static int formatBits(char ecl, int msk) {
        int data = FORMAT_BITS[levelIndex(ecl)] << 3 | msk;
        int rem = data;
        for (int i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
        return (data << 10 | rem) ^ 0x5412;
    }

    /** The 18 version bits for versions 7..40. */
    static int versionBits(int ver) {
        int rem = ver;
        for (int i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1F25);
        return ver << 12 | rem;
    }

    // ---- drawing ----
    private void setFunction(int x, int y, boolean dark) {
        modules[y][x] = dark;
        isFunction[y][x] = true;
    }

    private void drawFunctionPatterns() {
        for (int i = 0; i < size; i++) {
            setFunction(6, i, i % 2 == 0);
            setFunction(i, 6, i % 2 == 0);
        }
        drawFinder(3, 3);
        drawFinder(size - 4, 3);
        drawFinder(3, size - 4);
        int[] pos = alignmentPositions(version);
        int n = pos.length;
        for (int i = 0; i < n; i++) {
            for (int j = 0; j < n; j++) {
                if ((i == 0 && j == 0) || (i == 0 && j == n - 1) || (i == n - 1 && j == 0)) continue;
                for (int dy = -2; dy <= 2; dy++)
                    for (int dx = -2; dx <= 2; dx++)
                        setFunction(pos[i] + dx, pos[j] + dy, Math.max(Math.abs(dx), Math.abs(dy)) != 1);
            }
        }
        drawFormatBits(0);   // placeholder, replaced once the mask is chosen
        if (version >= 7) {
            int bits = versionBits(version);
            for (int i = 0; i < 18; i++) {
                boolean bit = ((bits >>> i) & 1) != 0;
                int a = size - 11 + i % 3;
                int b = i / 3;
                setFunction(a, b, bit);
                setFunction(b, a, bit);
            }
        }
    }

    private void drawFinder(int x, int y) {
        for (int dy = -4; dy <= 4; dy++) {
            for (int dx = -4; dx <= 4; dx++) {
                int dist = Math.max(Math.abs(dx), Math.abs(dy));
                int xx = x + dx, yy = y + dy;
                if (xx >= 0 && xx < size && yy >= 0 && yy < size) setFunction(xx, yy, dist != 2 && dist != 4);
            }
        }
    }

    private void drawFormatBits(int msk) {
        int bits = formatBits(ecl, msk);
        for (int i = 0; i <= 5; i++) setFunction(8, i, bit(bits, i));
        setFunction(8, 7, bit(bits, 6));
        setFunction(8, 8, bit(bits, 7));
        setFunction(7, 8, bit(bits, 8));
        for (int i = 9; i < 15; i++) setFunction(14 - i, 8, bit(bits, i));
        for (int i = 0; i < 8; i++) setFunction(size - 1 - i, 8, bit(bits, i));
        for (int i = 8; i < 15; i++) setFunction(8, size - 15 + i, bit(bits, i));
        setFunction(8, size - 8, true);   // the always-dark module
    }

    private static boolean bit(int x, int i) {
        return ((x >>> i) & 1) != 0;
    }

    private byte[] addEccAndInterleave(byte[] data) {
        int li = levelIndex(ecl);
        int numBlocks = NUM_ERROR_CORRECTION_BLOCKS[li][version];
        int blockEccLen = ECC_CODEWORDS_PER_BLOCK[li][version];
        int rawCodewords = numRawDataModules(version) / 8;
        int numShortBlocks = numBlocks - rawCodewords % numBlocks;
        int shortBlockLen = rawCodewords / numBlocks;
        byte[] divisor = reedSolomonDivisor(blockEccLen);
        byte[][] blocks = new byte[numBlocks][];
        for (int i = 0, k = 0; i < numBlocks; i++) {
            int datLen = shortBlockLen - blockEccLen + (i < numShortBlocks ? 0 : 1);
            byte[] dat = Arrays.copyOfRange(data, k, k + datLen);
            k += datLen;
            byte[] block = Arrays.copyOf(dat, shortBlockLen + 1);
            byte[] ecc = reedSolomonRemainder(dat, divisor);
            System.arraycopy(ecc, 0, block, block.length - blockEccLen, ecc.length);
            blocks[i] = block;
        }
        byte[] result = new byte[rawCodewords];
        for (int i = 0, k = 0; i < blocks[0].length; i++) {
            for (int j = 0; j < blocks.length; j++) {
                if (i != shortBlockLen - blockEccLen || j >= numShortBlocks) result[k++] = blocks[j][i];
            }
        }
        return result;
    }

    private void drawCodewords(byte[] data) {
        int i = 0;
        for (int right = size - 1; right >= 1; right -= 2) {
            if (right == 6) right = 5;
            for (int vert = 0; vert < size; vert++) {
                for (int j = 0; j < 2; j++) {
                    int x = right - j;
                    boolean upward = ((right + 1) & 2) == 0;
                    int y = upward ? size - 1 - vert : vert;
                    if (!isFunction[y][x] && i < data.length * 8) {
                        modules[y][x] = bit(data[i >>> 3], 7 - (i & 7));
                        i++;
                    }
                }
            }
        }
    }

    static boolean maskBit(int msk, int x, int y) {
        switch (msk) {
            case 0: return (x + y) % 2 == 0;
            case 1: return y % 2 == 0;
            case 2: return x % 3 == 0;
            case 3: return (x + y) % 3 == 0;
            case 4: return (x / 3 + y / 2) % 2 == 0;
            case 5: return x * y % 2 + x * y % 3 == 0;
            case 6: return (x * y % 2 + x * y % 3) % 2 == 0;
            case 7: return ((x + y) % 2 + x * y % 3) % 2 == 0;
            default: throw new IllegalArgumentException("mask");
        }
    }

    private void applyMask(int msk) {
        for (int y = 0; y < size; y++)
            for (int x = 0; x < size; x++)
                if (!isFunction[y][x] && maskBit(msk, x, y)) modules[y][x] = !modules[y][x];
    }

    private long penaltyScore() {
        long result = 0;
        // rule 1: runs of 5+ same colour; rule 3: finder-like 1:1:3:1:1 with 4 light modules on one side
        for (int pass = 0; pass < 2; pass++) {
            for (int a = 0; a < size; a++) {
                int run = 0;
                boolean prev = false;
                for (int b = 0; b < size; b++) {
                    boolean c = pass == 0 ? modules[a][b] : modules[b][a];
                    if (b == 0 || c != prev) {
                        if (run >= 5) result += 3 + (run - 5);
                        run = 1;
                        prev = c;
                    } else {
                        run++;
                    }
                }
                if (run >= 5) result += 3 + (run - 5);
                for (int b = -4; b < size; b++) {
                    if (finderLike(pass, a, b)) result += 40;
                }
            }
        }
        // rule 2: 2x2 blocks
        for (int y = 0; y < size - 1; y++)
            for (int x = 0; x < size - 1; x++) {
                boolean c = modules[y][x];
                if (c == modules[y][x + 1] && c == modules[y + 1][x] && c == modules[y + 1][x + 1]) result += 3;
            }
        // rule 4: dark balance
        int dark = 0;
        for (boolean[] row : modules) for (boolean m : row) if (m) dark++;
        int total = size * size;
        int k = (Math.abs(dark * 20 - total * 10) + total - 1) / total - 1;
        result += (long) k * 10;
        return result;
    }

    private static final boolean[] FINDER_A = {true, false, true, true, true, false, true, false, false, false, false};
    private static final boolean[] FINDER_B = {false, false, false, false, true, false, true, true, true, false, true};

    private boolean finderLike(int pass, int a, int start) {
        return matches(pass, a, start, FINDER_A) || matches(pass, a, start, FINDER_B);
    }

    private boolean matches(int pass, int a, int start, boolean[] pat) {
        for (int i = 0; i < pat.length; i++) {
            int b = start + i;
            boolean c = b >= 0 && b < size && (pass == 0 ? modules[a][b] : modules[b][a]);   // outside counts as light
            if (c != pat[i]) return false;
        }
        return true;
    }

    // ---- Reed-Solomon over GF(2^8), polynomial 0x11D ----
    static byte[] reedSolomonDivisor(int degree) {
        byte[] result = new byte[degree];
        result[degree - 1] = 1;
        int root = 1;
        for (int i = 0; i < degree; i++) {
            for (int j = 0; j < result.length; j++) {
                result[j] = (byte) gfMul(result[j] & 0xFF, root);
                if (j + 1 < result.length) result[j] ^= result[j + 1];
            }
            root = gfMul(root, 0x02);
        }
        return result;
    }

    static byte[] reedSolomonRemainder(byte[] data, byte[] divisor) {
        byte[] result = new byte[divisor.length];
        for (byte b : data) {
            int factor = (b ^ result[0]) & 0xFF;
            System.arraycopy(result, 1, result, 0, result.length - 1);
            result[result.length - 1] = 0;
            for (int i = 0; i < result.length; i++) result[i] ^= (byte) gfMul(divisor[i] & 0xFF, factor);
        }
        return result;
    }

    static int gfMul(int x, int y) {
        int z = 0;
        for (int i = 7; i >= 0; i--) {
            z = (z << 1) ^ ((z >>> 7) * 0x11D);
            z ^= ((y >>> i) & 1) * x;
        }
        return z & 0xFF;
    }

    private static final class BitBuf {
        byte[] buf = new byte[64];
        int len;

        void append(int val, int n) {
            for (int i = n - 1; i >= 0; i--) {
                if ((len >>> 3) >= buf.length) buf = Arrays.copyOf(buf, buf.length * 2);
                if (((val >>> i) & 1) != 0) buf[len >>> 3] |= (byte) (0x80 >>> (len & 7));
                len++;
            }
        }

        byte[] toBytes() {
            return Arrays.copyOf(buf, len / 8);
        }
    }
}

/* CPython's Mersenne Twister, reproduced exactly, so the browser can recompute the
 * manuscript's confidence intervals rather than approximate them.
 *
 * WHY THIS FILE EXISTS
 *
 * The frozen analysis drew its bootstrap replicates with Python's random.Random(seed).
 * An interval is only reproducible if the draw sequence is reproducible, so a page that
 * used a different generator could match the point estimate and still print different
 * interval endpoints. Rather than ship that difference and explain it away, this is
 * MT19937 with CPython's init_by_array seeding and CPython's rejection sampling in
 * randrange, which makes the browser's replicate sequence identical to Python's.
 *
 * tests/test_browser_bootstrap_parity.py asserts the equality against Python directly,
 * so the claim is checked rather than asserted.
 */
(function (root) {
  "use strict";
  var N = 624, M = 397, MATRIX_A = 0x9908b0df, UPPER = 0x80000000, LOWER = 0x7fffffff;

  function MT(seed) {
    this.mt = new Uint32Array(N);
    this.mti = N + 1;
    this.initByArray(seedKey(seed));
  }

  /* CPython splits the absolute value of an integer seed into 32-bit words. */
  function seedKey(seed) {
    var s = Math.abs(seed) >>> 0, key = [];
    if (seed === 0) return [0];
    var v = Math.abs(seed);
    while (v > 0) { key.push(v >>> 0 & 0xffffffff); v = Math.floor(v / 4294967296); }
    return key.length ? key : [s];
  }

  MT.prototype.initGenrand = function (s) {
    this.mt[0] = s >>> 0;
    for (this.mti = 1; this.mti < N; this.mti++) {
      var prev = this.mt[this.mti - 1] ^ (this.mt[this.mti - 1] >>> 30);
      this.mt[this.mti] = (Math.imul(1812433253, prev) + this.mti) >>> 0;
    }
  };

  MT.prototype.initByArray = function (key) {
    this.initGenrand(19650218);
    var i = 1, j = 0, k = Math.max(N, key.length);
    for (; k; k--) {
      var p = this.mt[i - 1] ^ (this.mt[i - 1] >>> 30);
      this.mt[i] = (((this.mt[i] ^ Math.imul(p, 1664525)) >>> 0) + key[j] + j) >>> 0;
      i++; j++;
      if (i >= N) { this.mt[0] = this.mt[N - 1]; i = 1; }
      if (j >= key.length) j = 0;
    }
    for (k = N - 1; k; k--) {
      var q = this.mt[i - 1] ^ (this.mt[i - 1] >>> 30);
      this.mt[i] = (((this.mt[i] ^ Math.imul(q, 1566083941)) >>> 0) - i) >>> 0;
      i++;
      if (i >= N) { this.mt[0] = this.mt[N - 1]; i = 1; }
    }
    this.mt[0] = UPPER;
  };

  MT.prototype.genrandUint32 = function () {
    var y, kk, mag01 = [0, MATRIX_A];
    if (this.mti >= N) {
      for (kk = 0; kk < N - M; kk++) {
        y = ((this.mt[kk] & UPPER) | (this.mt[kk + 1] & LOWER)) >>> 0;
        this.mt[kk] = (this.mt[kk + M] ^ (y >>> 1) ^ mag01[y & 1]) >>> 0;
      }
      for (; kk < N - 1; kk++) {
        y = ((this.mt[kk] & UPPER) | (this.mt[kk + 1] & LOWER)) >>> 0;
        this.mt[kk] = (this.mt[kk + (M - N)] ^ (y >>> 1) ^ mag01[y & 1]) >>> 0;
      }
      y = ((this.mt[N - 1] & UPPER) | (this.mt[0] & LOWER)) >>> 0;
      this.mt[N - 1] = (this.mt[M - 1] ^ (y >>> 1) ^ mag01[y & 1]) >>> 0;
      this.mti = 0;
    }
    y = this.mt[this.mti++];
    y ^= y >>> 11;
    y = (y ^ ((y << 7) & 0x9d2c5680)) >>> 0;
    y = (y ^ ((y << 15) & 0xefc60000)) >>> 0;
    y ^= y >>> 18;
    return y >>> 0;
  };

  /* CPython's getrandbits for k <= 32. */
  MT.prototype.getrandbits = function (k) {
    if (k <= 0) return 0;
    if (k > 32) throw new Error("getrandbits: k > 32 not needed here");
    return this.genrandUint32() >>> (32 - k);
  };

  /* CPython's _randbelow_with_getrandbits: reject until below n. The rejection loop is
   * part of the sequence; dropping it would consume a different number of words and
   * desynchronise every later draw. */
  MT.prototype.randrange = function (n) {
    if (n <= 0) throw new Error("randrange: n must be positive");
    /* CPython uses n.bit_length(), not (n-1).bit_length(). The two agree for many n
     * (21 and 20 both have 5 bits) and disagree at every exact power of two, where the
     * wrong one would silently consume a different number of random words. */
    var k = 32 - Math.clz32(n);
    var r = this.getrandbits(k);
    while (r >= n) r = this.getrandbits(k);
    return r;
  };

  root.MT19937 = MT;
})(typeof globalThis !== "undefined" ? globalThis : this);

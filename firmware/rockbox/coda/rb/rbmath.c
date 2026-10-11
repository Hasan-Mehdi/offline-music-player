/* Minimal libm for the plugin. Accuracy target: ~1e-12 relative for the double paths the
 * brain uses (exp/log/pow for recency decay, sqrt for norms), plenty for per-frame floats.
 * Not used on the host build, which links the real libm. */
#include <stdint.h>

#define LN2 0.69314718055994530942
#define PI 3.14159265358979323846

double fabs(double x) { return x < 0 ? -x : x; }
double fmax(double a, double b) { return a > b ? a : b; }

double floor(double x)
{
    if (x >= 9007199254740992.0 || x <= -9007199254740992.0) return x;
    int64_t i = (int64_t)x;
    return (double)(x < (double)i ? i - 1 : i);
}

double ceil(double x) { return -floor(-x); }

double sqrt(double x)
{
    if (x <= 0) return 0;
    /* initial guess from the exponent, then Newton */
    union { double d; uint64_t u; } v = { x };
    v.u = (v.u >> 1) + (1023ull << 51);
    double r = v.d;
    for (int i = 0; i < 6; i++) r = 0.5 * (r + x / r);
    return r;
}

double exp(double x)
{
    if (x > 709) return 1.7976931348623157e308;
    if (x < -745) return 0;
    /* x = k ln2 + r, |r| <= ln2/2; e^r by Taylor (r small) */
    double kf = floor(x / LN2 + 0.5);
    int k = (int)kf;
    double r = x - kf * LN2, term = 1, sum = 1;
    for (int n = 1; n < 22; n++) { term *= r / n; sum += term; }
    union { double d; uint64_t u; } s;
    if (k > 1023) { k -= 1023; sum *= 8.98846567431158e307; }
    if (k < -1022) { k += 1022; sum *= 2.2250738585072014e-308; }
    s.u = (uint64_t)(k + 1023) << 52;
    return sum * s.d;
}

double log(double x)
{
    if (x <= 0) return -1.7976931348623157e308;
    union { double d; uint64_t u; } v = { x };
    int e = (int)((v.u >> 52) & 2047) - 1023;
    v.u = (v.u & ((1ull << 52) - 1)) | (1023ull << 52);   /* mantissa in [1, 2) */
    double m = v.d;
    if (m > 1.41421356237309504880) { m *= 0.5; e++; }
    /* ln(m) = 2 atanh((m-1)/(m+1)) */
    double t = (m - 1) / (m + 1), t2 = t * t, term = t, sum = 0;
    for (int n = 1; n < 40; n += 2) { sum += term / n; term *= t2; }
    return 2 * sum + e * LN2;
}

double pow(double x, double y)
{
    if (y == 0) return 1;
    if (x == 0) return 0;
    if (x < 0) {
        double yi = floor(y);
        if (yi != y) return 0;                  /* no complex results */
        double r = exp(y * log(-x));
        return ((int64_t)yi & 1) ? -r : r;
    }
    return exp(y * log(x));
}

static double reduce(double x)       /* to [-pi, pi] */
{
    double k = floor(x / (2 * PI) + 0.5);
    return x - k * 2 * PI;
}

double sin(double x)
{
    x = reduce(x);
    double term = x, sum = x, x2 = x * x;
    for (int n = 1; n < 14; n++) { term *= -x2 / ((2 * n) * (2 * n + 1)); sum += term; }
    return sum;
}

double cos(double x) { return sin(x + PI / 2); }

double atan(double x)
{
    int neg = x < 0;
    if (neg) x = -x;
    int inv = x > 1;
    if (inv) x = 1 / x;
    /* atan(x) = 2 atan(x / (1 + sqrt(1 + x^2))) halves the argument; then series */
    double h = x / (1 + sqrt(1 + x * x));
    double h2 = h * h, term = h, sum = 0;
    for (int n = 1; n < 60; n += 2) { sum += term / n; term *= -h2; }
    double r = 2 * sum;
    if (inv) r = PI / 2 - r;
    return neg ? -r : r;
}

float expf(float x) { return (float)exp(x); }
float sinf(float x) { return (float)sin(x); }
float cosf(float x) { return (float)cos(x); }
float sqrtf(float x) { return (float)sqrt(x); }
float fabsf(float x) { return x < 0 ? -x : x; }
float fmaxf(float a, float b) { return a > b ? a : b; }
float floorf(float x) { return (float)floor(x); }
float ceilf(float x) { return (float)ceil(x); }
long lrintf(float x) { return (long)(x < 0 ? x - 0.5f : x + 0.5f); }

double tanh(double x)
{
    if (x > 20) return 1;
    if (x < -20) return -1;
    double e = exp(2 * x);
    return (e - 1) / (e + 1);
}

double fmin(double a, double b) { return a < b ? a : b; }
double log2(double x) { return log(x) * 1.4426950408889634; }   /* engine v3 tempo term */

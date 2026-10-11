/* Force-included (-include) into every Coda source when built as a Rockbox plugin:
 * maps the bits of libc the portable code uses onto the plugin API, TLSF and the
 * small maths library in rbmath.c (Rockbox has no libm; the X1000 build is soft-float). */
#ifndef CODA_RBCOMPAT_H
#define CODA_RBCOMPAT_H

#include "plugin.h"
#include "lib/stdio_compat.h"
#include <math.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <tlsf.h>

/* headers are in; now the renames (after, so prototypes above stay intact) */
#define malloc tlsf_malloc
#define calloc tlsf_calloc
#define realloc tlsf_realloc
#define free tlsf_free
#define qsort rb->qsort
#define strtol rb->strtol
#define strstr rb->strstr
#define strchr rb->strchr
#define strcmp rb->strcmp
#define strncmp rb->strncmp
#define strlen rb->strlen
#define memcmp rb->memcmp
#define memmove rb->memmove
#define snprintf rb->snprintf
#define vsnprintf rb->vsnprintf

double pow(double x, double y);
double exp(double x);
double log(double x);
double sqrt(double x);
double fabs(double x);
double fmax(double a, double b);
double fmin(double a, double b);
double log2(double x);
double floor(double x);
double ceil(double x);
double sin(double x);
double cos(double x);
double atan(double x);
double tanh(double x);
float expf(float x);
float sinf(float x);
float cosf(float x);
float sqrtf(float x);
float fabsf(float x);
float fmaxf(float a, float b);
float floorf(float x);
float ceilf(float x);
long lrintf(float x);

#endif

// DCTL runtime stub — approximates Resolve's DCTL environment closely enough
// for clang to catch syntax/type errors in generated .dctl files.
// Usage: clang++ -std=c++14 -fsyntax-only -include dctl_stub.h <file.dctl as cpp>
#pragma once

#define __DEVICE__ inline
#define __CONSTANT__ static const
#define __CONSTANTREF__ const

struct float2 { float x, y; };
struct float3 { float x, y, z; };
struct float4 { float x, y, z, w; };

inline float2 make_float2(float x, float y) { return {x, y}; }
inline float3 make_float3(float x, float y, float z) { return {x, y, z}; }
inline float4 make_float4(float x, float y, float z, float w) { return {x, y, z, w}; }

// component-wise vector arithmetic (as documented in the DCTL README)
inline float3 operator+(float3 a, float3 b) { return {a.x+b.x, a.y+b.y, a.z+b.z}; }
inline float3 operator-(float3 a, float3 b) { return {a.x-b.x, a.y-b.y, a.z-b.z}; }
inline float3 operator*(float3 a, float3 b) { return {a.x*b.x, a.y*b.y, a.z*b.z}; }
inline float3 operator/(float3 a, float3 b) { return {a.x/b.x, a.y/b.y, a.z/b.z}; }
inline float3 operator*(float3 a, float s) { return {a.x*s, a.y*s, a.z*s}; }
inline float3 operator*(float s, float3 a) { return {a.x*s, a.y*s, a.z*s}; }
inline float3 operator/(float3 a, float s) { return {a.x/s, a.y/s, a.z/s}; }
inline float3 operator+(float3 a, float s) { return {a.x+s, a.y+s, a.z+s}; }
inline float3 operator-(float3 a, float s) { return {a.x-s, a.y-s, a.z-s}; }

#include <cmath>
inline float _fabs(float x) { return fabsf(x); }
inline float _powf(float x, float y) { return powf(x, y); }
inline float _logf(float x) { return logf(x); }
inline float _log2f(float x) { return log2f(x); }
inline float _expf(float x) { return expf(x); }
inline float _sqrtf(float x) { return sqrtf(x); }
inline float _fmaxf(float x, float y) { return fmaxf(x, y); }
inline float _fminf(float x, float y) { return fminf(x, y); }
inline float _clampf(float x, float lo, float hi) { return fminf(fmaxf(x, lo), hi); }
inline float _saturatef(float x) { return _clampf(x, 0.0f, 1.0f); }
inline float _floorf(float x) { return floorf(x); }
inline float _ceilf(float x) { return ceilf(x); }
inline float _fmod(float x, float y) { return fmodf(x, y); }
inline float _cosf(float x) { return cosf(x); }
inline float _sinf(float x) { return sinf(x); }
inline float _mix(float x, float y, float a) { return x + (y - x) * a; }
// NOTE: deliberately NO float3 overload of _mix — matches the conservative
// reading of the README; generated code must not rely on vector _mix.

typedef unsigned int uint;
inline float RAND(uint seed) { return (seed % 1000u) / 1000.0f; }
static const int TIMELINE_FRAME_INDEX = 1;

// integer helpers (documented: no underscore prefix)
inline int abs(int x) { return x < 0 ? -x : x; }
inline int min(int a, int b) { return a < b ? a : b; }
inline int max(int a, int b) { return a > b ? a : b; }

// UI param macros expand to plain variable declarations
#define _UI_JOIN(a, b) a##b
#define DCTLUI_SLIDER_FLOAT 0
#define DCTLUI_SLIDER_INT 1
#define DCTLUI_CHECK_BOX 2
#define DCTLUI_VALUE_BOX 3
#define DCTLUI_COMBO_BOX 4
#define DCTLUI_COLOR_PICKER 5

struct _ui_color { float r, g, b; };

// variadic dispatch: sliders/checkbox/valuebox -> float; color picker -> struct
#define _SELECT_UI(_1, _2, _3, _4, _5, _6, _7, NAME, ...) NAME
#define _UI_7(var, label, type, def, mn, mx, step) static const float var = (float)(def);
#define _UI_6(var, label, type, r, g, b) static const _ui_color var = {(float)(r), (float)(g), (float)(b)};
#define _UI_4(var, label, type, def) static const float var = (float)(def);
#define DEFINE_UI_PARAMS(...) _SELECT_UI(__VA_ARGS__, _UI_7, _UI_6, _UI_5_UNUSED, _UI_4, _UI_3_UNUSED)(__VA_ARGS__)

// bind.h -- the binding engine: tag values -> widget properties, with the
// semantics designer/generators/qml_generator.py gives generated QML
// (that file is the specification; kit_schema.json carries its tables).
//
// Rules, implemented in bind.c:
//   1. Reading. display = tag * multiplier + offset. Unseen tag: a str-typed
//      property (not "value", no scaling, no format) reads ""; anything
//      else reads 0. A "format" ("%1 km") replaces %1 with the reading.
//   2. Units. A binding with a unit sets the widget's "unit" (or "units")
//      property when the schema has one and it is not itself bound.
//   3. Thresholds. warning/critical are "<op> <number>" with op in
//      > >= < <= == != (parse_threshold). For the types in
//      state_properties, the state property becomes levels[2] when critical
//      trips, else levels[1] when warning trips, else levels[0]; ShAnnunciator
//      also gets lit = any trip. For threshold_properties, a threshold whose
//      op is listed sets the named property to the threshold's number.
//   4. Series. (type, prop) in series_properties bind to the tag's history
//      (last maxPoints values) or to the active alarms; deliver a HMI_V_LIST.
//   5. Two-way state. A control whose state property is bound and also
//      written by a "write" action on the same tag keeps showing the tag.
//   6. Sim tags ("sim.*") are Designer-only; treat as unbound (fallback).
//   7. ShTripInfo "value" -> "row1Value" as a string with one decimal.
//   Property aliases the generator applies (ShStatDot.active -> state, ...)
//   are the kit's business: widgets accept the model's property names.
#pragma once

#include "model.h"
#include "tags.h"

typedef struct hmi_bind hmi_bind_t;

// Callback the engine uses to push a property into a widget.
typedef void (*hmi_bind_apply_cb)(hmi_widget_t *w, const char *prop, const hmi_value_t *value, void *user);

hmi_bind_t *hmi_bind_create(hmi_bind_apply_cb apply, void *user);
void hmi_bind_destroy(hmi_bind_t *b);

// Registers every binding of a page (and unregisters the previous page's).
// Applies the initial (fallback) values immediately.
void hmi_bind_page(hmi_bind_t *b, hmi_page_t *page);

// A tag changed: re-evaluate every binding on it and push the results.
void hmi_bind_on_tag(hmi_bind_t *b, const char *tag, const hmi_value_t *value);

// Parse "> 6.5" -> op, number. Returns false for "" or malformed.
bool hmi_bind_parse_threshold(const char *text, char op[3], double *number);
// Evaluate "<value> <op> <number>".
bool hmi_bind_threshold_trips(double value, const char *op, double number);

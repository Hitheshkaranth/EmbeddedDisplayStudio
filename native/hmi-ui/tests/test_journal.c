// tests/test_journal.c -- CONTRACT 13.3 alarm journal file format, recent(),
// rotation. Wave 1 gate for W3 (FROZEN).
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

#include "cJSON.h"
#include "check.h"
#include "journal.h"

static char *read_all(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *b = malloc((size_t)n + 1);
    fread(b, 1, (size_t)n, f);
    b[n] = 0;
    fclose(f);
    return b;
}

static long size_of(const char *path)
{
    struct stat st;
    return stat(path, &st) == 0 ? (long)st.st_size : -1;
}

int main(void)
{
    CHECK(hmi_journal_open(NULL, 100) == NULL);
    CHECK(hmi_journal_open("", 100) == NULL);
    CHECK(!hmi_journal_append(NULL, 1, "raise", "a.b", "A", "warning", 3, NULL));
    hmi_value_t empty = hmi_journal_recent(NULL, 5);
    CHECK(empty.kind == HMI_V_LIST && empty.count == 0);

    char dir[] = "/tmp/hmi-jn-XXXXXX";
    CHECK(mkdtemp(dir) != NULL);
    char path[600], old[610];
    snprintf(path, sizeof path, "%s/alarm-journal.jsonl", dir);
    snprintf(old, sizeof old, "%s.1", path);

    hmi_journal_t *j = hmi_journal_open(path, HMI_JOURNAL_MAX_BYTES);
    CHECK(j != NULL);
    hmi_value_t v = hmi_value_num(9.5);
    CHECK(hmi_journal_append(j, 1790569717123LL, "raise", "eng.egt", "EGT", "critical", 1, &v));
    hmi_value_t s = hmi_value_str("OPEN");
    CHECK(hmi_journal_append(j, 1790569718000LL, "ack", "door.state", "Door \"A\"", "warning", 3, &s));
    hmi_value_free(&s);

    // one JSON object per line, flushed at once (readable before close)
    char *text = read_all(path);
    CHECK(text != NULL);
    int lines = 0;
    for (char *line = text ? strtok(text, "\n") : NULL; line; line = strtok(NULL, "\n")) {
        cJSON *o = cJSON_Parse(line);
        CHECK(cJSON_IsObject(o));
        if (lines == 0 && o) {
            CHECK(cJSON_GetObjectItem(o, "ts")->valuedouble == 1790569717123.0);
            CHECK_EQ_STR(cJSON_GetStringValue(cJSON_GetObjectItem(o, "event")), "raise");
            CHECK_EQ_STR(cJSON_GetStringValue(cJSON_GetObjectItem(o, "tag")), "eng.egt");
            CHECK_EQ_STR(cJSON_GetStringValue(cJSON_GetObjectItem(o, "label")), "EGT");
            CHECK_EQ_STR(cJSON_GetStringValue(cJSON_GetObjectItem(o, "severity")), "critical");
            CHECK(cJSON_GetObjectItem(o, "priority")->valueint == 1);
            CHECK(cJSON_GetObjectItem(o, "value")->valuedouble == 9.5);
        }
        if (lines == 1 && o)
            CHECK_EQ_STR(cJSON_GetStringValue(cJSON_GetObjectItem(o, "label")), "Door \"A\"");
        cJSON_Delete(o);
        ++lines;
    }
    CHECK(lines == 2);
    free(text);

    // recent(): newest first, 9-field items
    hmi_value_t r = hmi_journal_recent(j, 10);
    CHECK(r.kind == HMI_V_LIST && r.count == 2);
    if (r.count == 2) {
        const hmi_value_t *it = &r.items[0];
        CHECK(it->count == 9);
        if (it->count == 9) {
            CHECK_EQ_STR(hmi_value_as_str(&it->items[0], ""), "door.state");
            CHECK_EQ_STR(hmi_value_as_str(&it->items[2], ""), "warning");
            CHECK_EQ_STR(hmi_value_as_str(&it->items[3], ""), "OPEN");
            CHECK_EQ_STR(hmi_value_as_str(&it->items[4], ""), "ack");
            CHECK(strlen(hmi_value_as_str(&it->items[5], "")) == 19);   // YYYY-MM-DDTHH:MM:SS
            CHECK(it->items[6].kind == HMI_V_BOOL && it->items[6].b);
            CHECK_NEAR(it->items[7].n, 3, 1e-9);
            CHECK_EQ_STR(hmi_value_as_str(&it->items[8], ""), "cleared");
        }
    }
    hmi_value_free(&r);
    r = hmi_journal_recent(j, 1);
    CHECK(r.count == 1);
    hmi_value_free(&r);

    // a garbage line is skipped
    FILE *f = fopen(path, "a");
    fputs("not json\n", f);
    fclose(f);
    r = hmi_journal_recent(j, 10);
    CHECK(r.count == 2);
    hmi_value_free(&r);
    hmi_journal_close(j);

    // rotation at max_bytes: PATH.1 holds the old events, PATH starts over
    j = hmi_journal_open(path, 600);
    for (int i = 0; i < 12; i++) {
        hmi_value_t n = hmi_value_num(i);
        hmi_journal_append(j, 1790569720000LL + i, "raise", "r.x", "Rot", "warning", 3, &n);
    }
    CHECK(size_of(old) > 0);
    CHECK(size_of(path) < 600 + 200);
    r = hmi_journal_recent(j, 50);                 // reads PATH then PATH.1
    CHECK(r.count >= 10);
    if (r.count >= 1 && r.items[0].count == 9)
        CHECK_NEAR(r.items[0].items[3].n, 11, 1e-9);   // newest first across files
    hmi_value_free(&r);
    hmi_journal_close(j);

    remove(path); remove(old); rmdir(dir);
    return check_summary("test_journal");
}

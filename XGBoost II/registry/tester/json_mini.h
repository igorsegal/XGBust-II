// json_mini.h - минимальный разборщик JSON (без внешних библиотек).
// Поддержка: объекты, массивы, строки (UTF-8, \uXXXX как есть в UTF-8 для BMP), числа, true/false/null.
#pragma once
#include <string>
#include <vector>
#include <map>
#include <stdexcept>
#include <cstdlib>
#include <cstdio>
#include <fstream>
#include <sstream>

struct JV {
    enum T { NUL, BOOL, NUM, STR, ARR, OBJ } t = NUL;
    bool b = false;
    double n = 0;
    std::string s;
    std::vector<JV> a;
    std::map<std::string, JV> o;

    bool has(const std::string& k) const { return t == OBJ && o.count(k); }
    const JV& at(const std::string& k) const {
        auto it = o.find(k);
        if (t != OBJ || it == o.end()) throw std::runtime_error("JSON: нет ключа '" + k + "'");
        return it->second;
    }
    double num(double def) const { return t == NUM ? n : (t == BOOL ? (b ? 1 : 0) : def); }
    std::string str(const std::string& def = "") const { return t == STR ? s : def; }
    bool boolean(bool def) const { return t == BOOL ? b : (t == NUM ? n != 0 : def); }
};

class JParser {
    const std::string& x; size_t p = 0;
    void ws() { while (p < x.size() && (x[p] == ' ' || x[p] == '\n' || x[p] == '\r' || x[p] == '\t')) ++p; }
    [[noreturn]] void fail(const char* m) { throw std::runtime_error(std::string("JSON позиция ") + std::to_string(p) + ": " + m); }
    void enc(std::string& r, unsigned cp) {
        if (cp < 0x80) r += (char)cp;
        else if (cp < 0x800) { r += (char)(0xC0 | (cp >> 6)); r += (char)(0x80 | (cp & 0x3F)); }
        else { r += (char)(0xE0 | (cp >> 12)); r += (char)(0x80 | ((cp >> 6) & 0x3F)); r += (char)(0x80 | (cp & 0x3F)); }
    }
    std::string rstr() {
        std::string r; ++p;
        while (p < x.size() && x[p] != '"') {
            char c = x[p++];
            if (c == '\\') {
                if (p >= x.size()) fail("обрыв строки");
                char e = x[p++];
                switch (e) {
                    case 'n': r += '\n'; break; case 't': r += '\t'; break; case 'r': r += '\r'; break;
                    case 'b': r += '\b'; break; case 'f': r += '\f'; break;
                    case 'u': { if (p + 4 > x.size()) fail("обрыв \\u"); unsigned cp = (unsigned)strtoul(x.substr(p, 4).c_str(), nullptr, 16); p += 4; enc(r, cp); break; }
                    default: r += e;
                }
            } else r += c;
        }
        if (p >= x.size()) fail("строка не закрыта");
        ++p; return r;
    }
public:
    explicit JParser(const std::string& s) : x(s) {
        if (x.size() >= 3 && (unsigned char)x[0] == 0xEF && (unsigned char)x[1] == 0xBB && (unsigned char)x[2] == 0xBF) p = 3;
    }
    JV parse() { JV v = val(); ws(); if (p != x.size()) fail("лишние символы после JSON"); return v; }
    JV val() {
        ws(); if (p >= x.size()) fail("неожиданный конец");
        JV v; char c = x[p];
        if (c == '{') {
            v.t = JV::OBJ; ++p; ws();
            if (p < x.size() && x[p] == '}') { ++p; return v; }
            while (true) {
                ws(); if (p >= x.size() || x[p] != '"') fail("ожидался ключ");
                std::string k = rstr(); ws();
                if (p >= x.size() || x[p] != ':') fail("ожидалось ':'");
                ++p; v.o[k] = val(); ws();
                if (p < x.size() && x[p] == ',') { ++p; continue; }
                if (p < x.size() && x[p] == '}') { ++p; break; }
                fail("ожидалось ',' или '}'");
            }
        } else if (c == '[') {
            v.t = JV::ARR; ++p; ws();
            if (p < x.size() && x[p] == ']') { ++p; return v; }
            while (true) {
                v.a.push_back(val()); ws();
                if (p < x.size() && x[p] == ',') { ++p; continue; }
                if (p < x.size() && x[p] == ']') { ++p; break; }
                fail("ожидалось ',' или ']'");
            }
        } else if (c == '"') { v.t = JV::STR; v.s = rstr(); }
        else if (x.compare(p, 4, "true") == 0) { v.t = JV::BOOL; v.b = true; p += 4; }
        else if (x.compare(p, 5, "false") == 0) { v.t = JV::BOOL; v.b = false; p += 5; }
        else if (x.compare(p, 4, "null") == 0) { v.t = JV::NUL; p += 4; }
        else {
            char* e = nullptr; v.n = strtod(x.c_str() + p, &e);
            if (e == x.c_str() + p) fail("не число");
            v.t = JV::NUM; p = e - x.c_str();
        }
        return v;
    }
};

inline JV json_load(const std::string& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) throw std::runtime_error("не открыть файл: " + path);
    std::stringstream ss; ss << f.rdbuf();
    std::string s = ss.str();
    return JParser(s).parse();
}

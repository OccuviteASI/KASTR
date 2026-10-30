# -*- coding: utf-8 -*-
"""0.21.96 SCHEDULED MEETINGS -- time zones without a tz database download.

Kenton (2026-10-28): a meeting is scheduled "for a weekly/daily meeting, or just a 1 time meeting". A meeting keeps its time
zone's NAME (an IANA name such as America/Denver) plus the LOCAL wall time it starts at, so a weekly 09:00 stays 09:00 across a
daylight-saving change. This module turns (zone, local wall time) into UTC and back.

Windows Python ships no tz database (zoneinfo.ZoneInfo("America/Denver") fails there without the tzdata package), so the
rule each zone follows from now on is bundled below: every zone file's POSIX TZ footer (e.g. "MST7MDT,M3.2.0,M11.1.0"),
generated from the IANA tz database -- not downloaded at run time. zoneinfo is used whenever it loads (a Linux hub, or a
Windows Python with tzdata); the bundled rule otherwise. A POSIX rule is the zone's CURRENT rule: right for every meeting from
now on, not for history (a meeting is never scheduled into the past).

Wall times that do not exist (the spring-forward gap) move forward by the gap, as zoneinfo does with fold=0 (02:30 on the
spring-forward day in Denver is 03:30 MDT); wall times that happen twice (the fall-back hour) mean the FIRST one (daylight).
"""
import calendar
import datetime as _dt
import re

# Generated from the IANA tz database 2026e (WSL /usr/share/zoneinfo: each zone file's POSIX footer -- the rule it
# follows from now on). Regenerate the same way when the rules change.
TZDATA_VER = '2026e'
_RULES = (
    '<+00>0',
    '<+00>0<+02>-2,M3.5.0/1,M10.5.0/3',
    '<+01>-1',
    '<+02>-2',
    '<+0330>-3:30',
    '<+03>-3',
    '<+0430>-4:30',
    '<+04>-4',
    '<+0530>-5:30',
    '<+0545>-5:45',
    '<+05>-5',
    '<+0630>-6:30',
    '<+06>-6',
    '<+07>-7',
    '<+0845>-8:45',
    '<+08>-8',
    '<+09>-9',
    '<+1030>-10:30<+11>-11,M10.1.0,M4.1.0',
    '<+10>-10',
    '<+11>-11',
    '<+11>-11<+12>,M10.1.0,M4.1.0/3',
    '<+1245>-12:45<+1345>,M9.5.0/2:45,M4.1.0/3:45',
    '<+12>-12',
    '<+13>-13',
    '<+14>-14',
    '<-00>0',
    '<-01>1',
    '<-01>1<+00>,M3.5.0/0,M10.5.0/1',
    '<-02>2',
    '<-02>2<-01>,M3.5.0/-1,M10.5.0/0',
    '<-03>3',
    '<-03>3<-02>,M3.2.0,M11.1.0',
    '<-04>4',
    '<-04>4<-03>,M9.1.6/24,M4.1.6/24',
    '<-05>5',
    '<-06>6',
    '<-06>6<-05>,M9.1.6/22,M4.1.6/22',
    '<-07>7',
    '<-08>8',
    '<-0930>9:30',
    '<-09>9',
    '<-10>10',
    '<-11>11',
    '<-12>12',
    'ACST-9:30',
    'ACST-9:30ACDT,M10.1.0,M4.1.0/3',
    'AEST-10',
    'AEST-10AEDT,M10.1.0,M4.1.0/3',
    'AKST9AKDT,M3.2.0,M11.1.0',
    'AST4',
    'AST4ADT,M3.2.0,M11.1.0',
    'AWST-8',
    'CAT-2',
    'CET-1',
    'CET-1CEST,M3.5.0,M10.5.0/3',
    'CST-8',
    'CST5CDT,M3.2.0/0,M11.1.0/1',
    'CST6',
    'CST6CDT,M3.2.0,M11.1.0',
    'ChST-10',
    'EAT-3',
    'EET-2',
    'EET-2EEST,M3.4.4/50,M10.4.4/50',
    'EET-2EEST,M3.5.0/0,M10.5.0/0',
    'EET-2EEST,M3.5.0/3,M10.5.0/4',
    'EET-2EEST,M4.5.5/0,M10.5.4/24',
    'EST5',
    'EST5EDT,M3.2.0,M11.1.0',
    'GMT0',
    'GMT0BST,M3.5.0/1,M10.5.0',
    'HKT-8',
    'HST10',
    'HST10HDT,M3.2.0,M11.1.0',
    'IST-1GMT0,M10.5.0,M3.5.0/1',
    'IST-2IDT,M3.4.4/26,M10.5.0',
    'IST-5:30',
    'JST-9',
    'KST-9',
    'MSK-3',
    'MST7',
    'MST7MDT,M3.2.0,M11.1.0',
    'NST3:30NDT,M3.2.0,M11.1.0',
    'NZST-12NZDT,M9.5.0,M4.1.0/3',
    'PKT-5',
    'PST-8',
    'PST8PDT,M3.2.0,M11.1.0',
    'SAST-2',
    'SST11',
    'UTC0',
    'WAT-1',
    'WET0WEST,M3.5.0/1,M10.5.0',
    'WIB-7',
    'WIT-9',
    'WITA-8',
)
_ZONES = {
    'Africa/Abidjan': 68, 'Africa/Accra': 68, 'Africa/Addis_Ababa': 60, 'Africa/Algiers': 53, 'Africa/Asmara': 60,
    'Africa/Bamako': 68, 'Africa/Bangui': 89, 'Africa/Banjul': 68, 'Africa/Bissau': 68, 'Africa/Blantyre': 52,
    'Africa/Brazzaville': 89, 'Africa/Bujumbura': 52, 'Africa/Cairo': 65, 'Africa/Casablanca': 0, 'Africa/Ceuta': 54,
    'Africa/Conakry': 68, 'Africa/Dakar': 68, 'Africa/Dar_es_Salaam': 60, 'Africa/Djibouti': 60, 'Africa/Douala': 89,
    'Africa/El_Aaiun': 0, 'Africa/Freetown': 68, 'Africa/Gaborone': 52, 'Africa/Harare': 52, 'Africa/Johannesburg': 86,
    'Africa/Juba': 52, 'Africa/Kampala': 60, 'Africa/Khartoum': 52, 'Africa/Kigali': 52, 'Africa/Kinshasa': 89,
    'Africa/Lagos': 89, 'Africa/Libreville': 89, 'Africa/Lome': 68, 'Africa/Luanda': 89, 'Africa/Lubumbashi': 52,
    'Africa/Lusaka': 52, 'Africa/Malabo': 89, 'Africa/Maputo': 52, 'Africa/Maseru': 86, 'Africa/Mbabane': 86,
    'Africa/Mogadishu': 60, 'Africa/Monrovia': 68, 'Africa/Nairobi': 60, 'Africa/Ndjamena': 89, 'Africa/Niamey': 89,
    'Africa/Nouakchott': 68, 'Africa/Ouagadougou': 68, 'Africa/Porto-Novo': 89, 'Africa/Sao_Tome': 68, 'Africa/Timbuktu': 68,
    'Africa/Tripoli': 61, 'Africa/Tunis': 53, 'Africa/Windhoek': 52, 'America/Adak': 72, 'America/Anchorage': 48,
    'America/Anguilla': 49, 'America/Antigua': 49, 'America/Araguaina': 30, 'America/Argentina/Buenos_Aires': 30,
    'America/Argentina/Catamarca': 30, 'America/Argentina/Cordoba': 30, 'America/Argentina/Jujuy': 30, 'America/Argentina/La_Rioja': 30,
    'America/Argentina/Mendoza': 30, 'America/Argentina/Rio_Gallegos': 30, 'America/Argentina/Salta': 30, 'America/Argentina/San_Juan': 30,
    'America/Argentina/San_Luis': 30, 'America/Argentina/Tucuman': 30, 'America/Argentina/Ushuaia': 30, 'America/Aruba': 49,
    'America/Asuncion': 30, 'America/Atikokan': 66, 'America/Atka': 72, 'America/Bahia': 30, 'America/Bahia_Banderas': 57,
    'America/Barbados': 49, 'America/Belem': 30, 'America/Belize': 57, 'America/Blanc-Sablon': 49, 'America/Boa_Vista': 32,
    'America/Bogota': 34, 'America/Boise': 80, 'America/Cambridge_Bay': 80, 'America/Campo_Grande': 32, 'America/Cancun': 66,
    'America/Caracas': 32, 'America/Cayenne': 30, 'America/Cayman': 66, 'America/Chicago': 58, 'America/Chihuahua': 57,
    'America/Ciudad_Juarez': 80, 'America/Coral_Harbour': 66, 'America/Costa_Rica': 57, 'America/Coyhaique': 30,
    'America/Creston': 79, 'America/Cuiaba': 32, 'America/Curacao': 49, 'America/Danmarkshavn': 68, 'America/Dawson': 79,
    'America/Dawson_Creek': 79, 'America/Denver': 80, 'America/Detroit': 67, 'America/Dominica': 49, 'America/Edmonton': 57,
    'America/Eirunepe': 34, 'America/El_Salvador': 57, 'America/Ensenada': 85, 'America/Fort_Nelson': 79, 'America/Fortaleza': 30,
    'America/Glace_Bay': 50, 'America/Goose_Bay': 50, 'America/Grand_Turk': 67, 'America/Grenada': 49, 'America/Guadeloupe': 49,
    'America/Guatemala': 57, 'America/Guayaquil': 34, 'America/Guyana': 32, 'America/Halifax': 50, 'America/Havana': 56,
    'America/Hermosillo': 79, 'America/Indiana/Indianapolis': 67, 'America/Indiana/Knox': 58, 'America/Indiana/Marengo': 67,
    'America/Indiana/Petersburg': 67, 'America/Indiana/Tell_City': 58, 'America/Indiana/Vevay': 67, 'America/Indiana/Vincennes': 67,
    'America/Indiana/Winamac': 67, 'America/Inuvik': 57, 'America/Iqaluit': 67, 'America/Jamaica': 66, 'America/Juneau': 48,
    'America/Kentucky/Louisville': 67, 'America/Kentucky/Monticello': 67, 'America/Kralendijk': 49, 'America/La_Paz': 32,
    'America/Lima': 34, 'America/Los_Angeles': 85, 'America/Lower_Princes': 49, 'America/Maceio': 30, 'America/Managua': 57,
    'America/Manaus': 32, 'America/Marigot': 49, 'America/Martinique': 49, 'America/Matamoros': 58, 'America/Mazatlan': 79,
    'America/Menominee': 58, 'America/Merida': 57, 'America/Metlakatla': 48, 'America/Mexico_City': 57, 'America/Miquelon': 31,
    'America/Moncton': 50, 'America/Monterrey': 57, 'America/Montevideo': 30, 'America/Montreal': 67, 'America/Montserrat': 49,
    'America/Nassau': 67, 'America/New_York': 67, 'America/Nipigon': 67, 'America/Nome': 48, 'America/Noronha': 28,
    'America/North_Dakota/Beulah': 58, 'America/North_Dakota/Center': 58, 'America/North_Dakota/New_Salem': 58,
    'America/Nuuk': 29, 'America/Ojinaga': 58, 'America/Panama': 66, 'America/Pangnirtung': 67, 'America/Paramaribo': 30,
    'America/Phoenix': 79, 'America/Port-au-Prince': 67, 'America/Port_of_Spain': 49, 'America/Porto_Acre': 34,
    'America/Porto_Velho': 32, 'America/Puerto_Rico': 49, 'America/Punta_Arenas': 30, 'America/Rainy_River': 66,
    'America/Rankin_Inlet': 58, 'America/Recife': 30, 'America/Regina': 57, 'America/Resolute': 58, 'America/Rio_Branco': 34,
    'America/Santa_Isabel': 85, 'America/Santarem': 30, 'America/Santiago': 33, 'America/Santo_Domingo': 49,
    'America/Sao_Paulo': 30, 'America/Scoresbysund': 29, 'America/Shiprock': 80, 'America/Sitka': 48, 'America/St_Barthelemy': 49,
    'America/St_Johns': 81, 'America/St_Kitts': 49, 'America/St_Lucia': 49, 'America/St_Thomas': 49, 'America/St_Vincent': 49,
    'America/Swift_Current': 57, 'America/Tegucigalpa': 57, 'America/Thule': 50, 'America/Thunder_Bay': 67,
    'America/Tijuana': 85, 'America/Toronto': 67, 'America/Tortola': 49, 'America/Vancouver': 79, 'America/Virgin': 49,
    'America/Whitehorse': 79, 'America/Winnipeg': 66, 'America/Yakutat': 48, 'America/Yellowknife': 57, 'Antarctica/Casey': 15,
    'Antarctica/Davis': 13, 'Antarctica/DumontDUrville': 18, 'Antarctica/Macquarie': 47, 'Antarctica/Mawson': 10,
    'Antarctica/McMurdo': 82, 'Antarctica/Palmer': 30, 'Antarctica/Rothera': 30, 'Antarctica/Syowa': 5, 'Antarctica/Troll': 1,
    'Antarctica/Vostok': 10, 'Arctic/Longyearbyen': 54, 'Asia/Aden': 5, 'Asia/Almaty': 10, 'Asia/Amman': 5,
    'Asia/Anadyr': 22, 'Asia/Aqtau': 10, 'Asia/Aqtobe': 10, 'Asia/Ashgabat': 10, 'Asia/Atyrau': 10, 'Asia/Baghdad': 5,
    'Asia/Bahrain': 5, 'Asia/Baku': 7, 'Asia/Bangkok': 13, 'Asia/Barnaul': 13, 'Asia/Beirut': 63, 'Asia/Bishkek': 12,
    'Asia/Brunei': 15, 'Asia/Chita': 16, 'Asia/Chongqing': 55, 'Asia/Colombo': 8, 'Asia/Damascus': 5, 'Asia/Dhaka': 12,
    'Asia/Dili': 16, 'Asia/Dubai': 7, 'Asia/Dushanbe': 10, 'Asia/Famagusta': 64, 'Asia/Gaza': 62, 'Asia/Harbin': 55,
    'Asia/Hebron': 62, 'Asia/Ho_Chi_Minh': 13, 'Asia/Hong_Kong': 70, 'Asia/Hovd': 13, 'Asia/Irkutsk': 15, 'Asia/Istanbul': 5,
    'Asia/Jakarta': 91, 'Asia/Jayapura': 92, 'Asia/Jerusalem': 74, 'Asia/Kabul': 6, 'Asia/Kamchatka': 22, 'Asia/Karachi': 83,
    'Asia/Kashgar': 12, 'Asia/Kathmandu': 9, 'Asia/Khandyga': 16, 'Asia/Kolkata': 75, 'Asia/Krasnoyarsk': 13,
    'Asia/Kuala_Lumpur': 15, 'Asia/Kuching': 15, 'Asia/Kuwait': 5, 'Asia/Macau': 55, 'Asia/Magadan': 19, 'Asia/Makassar': 93,
    'Asia/Manila': 84, 'Asia/Muscat': 7, 'Asia/Nicosia': 64, 'Asia/Novokuznetsk': 13, 'Asia/Novosibirsk': 13,
    'Asia/Omsk': 12, 'Asia/Oral': 10, 'Asia/Phnom_Penh': 13, 'Asia/Pontianak': 91, 'Asia/Pyongyang': 77, 'Asia/Qatar': 5,
    'Asia/Qostanay': 10, 'Asia/Qyzylorda': 10, 'Asia/Riyadh': 5, 'Asia/Sakhalin': 19, 'Asia/Samarkand': 10,
    'Asia/Seoul': 77, 'Asia/Shanghai': 55, 'Asia/Singapore': 15, 'Asia/Srednekolymsk': 19, 'Asia/Taipei': 55,
    'Asia/Tashkent': 10, 'Asia/Tbilisi': 7, 'Asia/Tehran': 4, 'Asia/Tel_Aviv': 74, 'Asia/Thimphu': 12, 'Asia/Tokyo': 76,
    'Asia/Tomsk': 13, 'Asia/Ulaanbaatar': 15, 'Asia/Urumqi': 12, 'Asia/Ust-Nera': 18, 'Asia/Vientiane': 13,
    'Asia/Vladivostok': 18, 'Asia/Yakutsk': 16, 'Asia/Yangon': 11, 'Asia/Yekaterinburg': 10, 'Asia/Yerevan': 7,
    'Atlantic/Azores': 27, 'Atlantic/Bermuda': 50, 'Atlantic/Canary': 90, 'Atlantic/Cape_Verde': 26, 'Atlantic/Faroe': 90,
    'Atlantic/Jan_Mayen': 54, 'Atlantic/Madeira': 90, 'Atlantic/Reykjavik': 68, 'Atlantic/South_Georgia': 28,
    'Atlantic/St_Helena': 68, 'Atlantic/Stanley': 30, 'Australia/Adelaide': 45, 'Australia/Brisbane': 46, 'Australia/Broken_Hill': 45,
    'Australia/Canberra': 47, 'Australia/Currie': 47, 'Australia/Darwin': 44, 'Australia/Eucla': 14, 'Australia/Hobart': 47,
    'Australia/Lindeman': 46, 'Australia/Lord_Howe': 17, 'Australia/Melbourne': 47, 'Australia/Perth': 51,
    'Australia/Sydney': 47, 'Australia/Yancowinna': 45, 'Etc/GMT': 68, 'Etc/GMT+0': 68, 'Etc/GMT+1': 26, 'Etc/GMT+10': 41,
    'Etc/GMT+11': 42, 'Etc/GMT+12': 43, 'Etc/GMT+2': 28, 'Etc/GMT+3': 30, 'Etc/GMT+4': 32, 'Etc/GMT+5': 34,
    'Etc/GMT+6': 35, 'Etc/GMT+7': 37, 'Etc/GMT+8': 38, 'Etc/GMT+9': 40, 'Etc/GMT-0': 68, 'Etc/GMT-1': 2, 'Etc/GMT-10': 18,
    'Etc/GMT-11': 19, 'Etc/GMT-12': 22, 'Etc/GMT-13': 23, 'Etc/GMT-14': 24, 'Etc/GMT-2': 3, 'Etc/GMT-3': 5,
    'Etc/GMT-4': 7, 'Etc/GMT-5': 10, 'Etc/GMT-6': 12, 'Etc/GMT-7': 13, 'Etc/GMT-8': 15, 'Etc/GMT-9': 16, 'Etc/GMT0': 68,
    'Etc/Greenwich': 68, 'Etc/UCT': 88, 'Etc/UTC': 88, 'Etc/Universal': 88, 'Etc/Zulu': 88, 'Europe/Amsterdam': 54,
    'Europe/Andorra': 54, 'Europe/Astrakhan': 7, 'Europe/Athens': 64, 'Europe/Belfast': 69, 'Europe/Belgrade': 54,
    'Europe/Berlin': 54, 'Europe/Bratislava': 54, 'Europe/Brussels': 54, 'Europe/Bucharest': 64, 'Europe/Budapest': 54,
    'Europe/Busingen': 54, 'Europe/Chisinau': 64, 'Europe/Copenhagen': 54, 'Europe/Dublin': 73, 'Europe/Gibraltar': 54,
    'Europe/Guernsey': 69, 'Europe/Helsinki': 64, 'Europe/Isle_of_Man': 69, 'Europe/Istanbul': 5, 'Europe/Jersey': 69,
    'Europe/Kaliningrad': 61, 'Europe/Kirov': 78, 'Europe/Kyiv': 64, 'Europe/Lisbon': 90, 'Europe/Ljubljana': 54,
    'Europe/London': 69, 'Europe/Luxembourg': 54, 'Europe/Madrid': 54, 'Europe/Malta': 54, 'Europe/Mariehamn': 64,
    'Europe/Minsk': 5, 'Europe/Monaco': 54, 'Europe/Moscow': 78, 'Europe/Nicosia': 64, 'Europe/Oslo': 54, 'Europe/Paris': 54,
    'Europe/Podgorica': 54, 'Europe/Prague': 54, 'Europe/Riga': 64, 'Europe/Rome': 54, 'Europe/Samara': 7,
    'Europe/San_Marino': 54, 'Europe/Sarajevo': 54, 'Europe/Saratov': 7, 'Europe/Simferopol': 78, 'Europe/Skopje': 54,
    'Europe/Sofia': 64, 'Europe/Stockholm': 54, 'Europe/Tallinn': 64, 'Europe/Tirane': 54, 'Europe/Tiraspol': 64,
    'Europe/Ulyanovsk': 7, 'Europe/Vaduz': 54, 'Europe/Vatican': 54, 'Europe/Vienna': 54, 'Europe/Vilnius': 64,
    'Europe/Volgograd': 78, 'Europe/Warsaw': 54, 'Europe/Zagreb': 54, 'Europe/Zurich': 54, 'Factory': 25, 'GMT': 68,
    'Indian/Antananarivo': 60, 'Indian/Chagos': 12, 'Indian/Christmas': 13, 'Indian/Cocos': 11, 'Indian/Comoro': 60,
    'Indian/Kerguelen': 10, 'Indian/Mahe': 7, 'Indian/Maldives': 10, 'Indian/Mauritius': 7, 'Indian/Mayotte': 60,
    'Indian/Reunion': 7, 'Pacific/Apia': 23, 'Pacific/Auckland': 82, 'Pacific/Bougainville': 19, 'Pacific/Chatham': 21,
    'Pacific/Chuuk': 18, 'Pacific/Easter': 36, 'Pacific/Efate': 19, 'Pacific/Fakaofo': 23, 'Pacific/Fiji': 22,
    'Pacific/Funafuti': 22, 'Pacific/Galapagos': 35, 'Pacific/Gambier': 40, 'Pacific/Guadalcanal': 19, 'Pacific/Guam': 59,
    'Pacific/Honolulu': 71, 'Pacific/Johnston': 71, 'Pacific/Kanton': 23, 'Pacific/Kiritimati': 24, 'Pacific/Kosrae': 19,
    'Pacific/Kwajalein': 22, 'Pacific/Majuro': 22, 'Pacific/Marquesas': 39, 'Pacific/Midway': 87, 'Pacific/Nauru': 22,
    'Pacific/Niue': 42, 'Pacific/Norfolk': 20, 'Pacific/Noumea': 19, 'Pacific/Pago_Pago': 87, 'Pacific/Palau': 16,
    'Pacific/Pitcairn': 38, 'Pacific/Pohnpei': 19, 'Pacific/Port_Moresby': 18, 'Pacific/Rarotonga': 41, 'Pacific/Saipan': 59,
    'Pacific/Samoa': 87, 'Pacific/Tahiti': 41, 'Pacific/Tarawa': 22, 'Pacific/Tongatapu': 23, 'Pacific/Wake': 22,
    'Pacific/Wallis': 22, 'Pacific/Yap': 18, 'UTC': 88,
}


def zone_names():
    """Every zone name this module knows (sorted)."""
    return sorted(_ZONES)


def known(name):
    return isinstance(name, str) and (name in _ZONES or _zi(name) is not None)


_ZI = {}
_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+){0,2}$")


def _zi(name):
    """zoneinfo's zone when it loads here (None when it does not: Windows without tzdata)."""
    if not isinstance(name, str) or not _NAME_RE.match(name):
        return None
    if name in _ZI:
        return _ZI[name]
    z = None
    try:
        import zoneinfo
        z = zoneinfo.ZoneInfo(name)
    except Exception:
        z = None
    _ZI[name] = z
    return z


_ABBR_RE = re.compile(r"^(<[^>]*>|[A-Za-z]{3,})")
_OFF_RE = re.compile(r"^([+-]?)(\d{1,3})(?::(\d{1,2}))?(?::(\d{1,2}))?")


def _off(s):
    m = _OFF_RE.match(s)
    if not m:
        raise ValueError("bad offset")
    sec = int(m.group(2)) * 3600 + int(m.group(3) or 0) * 60 + int(m.group(4) or 0)
    return (-sec if m.group(1) == "-" else sec), s[m.end():]


def _rule_part(s):
    """'M3.2.0/2' | 'J60' | '59' -> (kind, a, b, c, secs) and the rest."""
    t = 7200
    if s.startswith("M"):
        m = re.match(r"^M(\d{1,2})\.(\d)\.(\d)", s)
        if not m:
            raise ValueError("bad rule")
        r = ("M", int(m.group(1)), int(m.group(2)), int(m.group(3)))
    elif s.startswith("J"):
        m = re.match(r"^J(\d{1,3})", s)
        if not m:
            raise ValueError("bad rule")
        r = ("J", int(m.group(1)), 0, 0)
    else:
        m = re.match(r"^(\d{1,3})", s)
        if not m:
            raise ValueError("bad rule")
        r = ("D", int(m.group(1)), 0, 0)
    s = s[m.end():]
    if s.startswith("/"):
        t, s = _off(s[1:])
    return r + (t,), s


_PARSED = {}


def parse(rule):
    """A POSIX TZ string -> {std, stdOff, dst, dstOff, start, end} (offsets in seconds EAST of UTC, as datetime counts)."""
    if rule in _PARSED:
        return _PARSED[rule]
    s = str(rule)
    m = _ABBR_RE.match(s)
    if not m:
        raise ValueError("bad zone rule")
    std = m.group(1).strip("<>")
    o, s = _off(s[m.end():])
    out = {"std": std, "stdOff": -o, "dst": None, "dstOff": -o, "start": None, "end": None}
    m = _ABBR_RE.match(s)
    if m:
        out["dst"] = m.group(1).strip("<>")
        s = s[m.end():]
        out["dstOff"] = out["stdOff"] + 3600
        if s and s[0] != ",":
            o2, s = _off(s)
            out["dstOff"] = -o2
        if s.startswith(","):
            a, s = _rule_part(s[1:])
            if not s.startswith(","):
                raise ValueError("bad zone rule")
            b, s = _rule_part(s[1:])
            out["start"], out["end"] = a, b
        else:   # no rule given: the US rule POSIX names as the default
            out["start"], out["end"] = ("M", 3, 2, 0, 7200), ("M", 11, 1, 0, 7200)
    _PARSED[rule] = out
    return out


def _day_of(part, year):
    """The date a rule part names in `year`."""
    kind, a, b, c, _t = part
    if kind == "M":
        first = _dt.date(year, a, 1)
        wd = (first.weekday() + 1) % 7          # 0 = Sunday, as POSIX counts
        d = 1 + (c - wd) % 7 + (b - 1) * 7
        last = calendar.monthrange(year, a)[1]
        while d > last:
            d -= 7
        return _dt.date(year, a, d)
    if kind == "J":   # 1..365, February 29 never counted
        d = _dt.date(year, 1, 1) + _dt.timedelta(days=a - 1)
        if calendar.isleap(year) and a >= 60:
            d += _dt.timedelta(days=1)
        return d
    return _dt.date(year, 1, 1) + _dt.timedelta(days=a)   # 0..365, February 29 counted


def _transitions(p, year):
    """The UTC epochs DST starts and ends in `year` (POSIX: the start read in standard time, the end in daylight time)."""
    a, b = p["start"], p["end"]
    s = calendar.timegm(_day_of(a, year).timetuple()) + a[4] - p["stdOff"]
    e = calendar.timegm(_day_of(b, year).timetuple()) + b[4] - p["dstOff"]
    return s, e


def _rule_offset(p, ts):
    if not p["dst"] or p["start"] is None:
        return p["stdOff"], False
    y = _dt.datetime(1970, 1, 1) + _dt.timedelta(seconds=ts + p["stdOff"])
    ev = []
    for yy in (y.year - 1, y.year, y.year + 1):
        s, e = _transitions(p, yy)
        ev += [(s, True), (e, False)]
    ev.sort()
    dst = not ev[0][1]
    for t, on in ev:
        if t > ts:
            break
        dst = on
    return (p["dstOff"] if dst else p["stdOff"]), dst


def rule_of(name):
    """The bundled POSIX rule of a zone ("" when unknown)."""
    i = _ZONES.get(name)
    return _RULES[i] if i is not None else ""


def offset(name, ts):
    """Seconds east of UTC in zone `name` at UTC epoch `ts` (0 for an unknown zone)."""
    z = _zi(name)
    if z is not None:
        try:
            return int(_dt.datetime.fromtimestamp(ts, z).utcoffset().total_seconds())
        except (OverflowError, OSError, ValueError):
            pass
    r = rule_of(name)
    return _rule_offset(parse(r), ts)[0] if r else 0


def to_local(name, ts):
    """UTC epoch -> (naive local wall time, offset seconds)."""
    o = offset(name, ts)
    return _dt.datetime(1970, 1, 1) + _dt.timedelta(seconds=ts + o), o


def to_utc(name, wall):
    """A naive local wall time in zone `name` -> the UTC epoch (a gap: moved forward by it; twice: the first)."""
    base = calendar.timegm(wall.timetuple())
    z = _zi(name)
    if z is not None:
        try:   # fold=0: a gap time is read with the offset before the gap (forward), a doubled time is the first one
            return int(round(wall.replace(tzinfo=z, fold=0).timestamp()))
        except (OverflowError, OSError, ValueError):
            pass
    r = rule_of(name)
    if not r:
        return base
    p = parse(r)
    cands = [base - o for o in {p["dstOff"], p["stdOff"]} if _rule_offset(p, base - o)[0] == o]
    if cands:
        return min(cands)
    return base - p["stdOff"]   # a gap: read with the offset before it (lands after the jump)


def abbr(name, ts):
    """The zone's abbreviation at `ts` (MST, MDT, ...) -- a hint for people, never used for math."""
    z = _zi(name)
    if z is not None:
        try:
            return _dt.datetime.fromtimestamp(ts, z).tzname() or ""
        except Exception:
            pass
    r = rule_of(name)
    if not r:
        return ""
    p = parse(r)
    return (p["dst"] if _rule_offset(p, ts)[1] else p["std"]) or ""


def vtimezone(name):
    """iCalendar VTIMEZONE lines for zone `name` from its POSIX rule -> a list of lines, or None when the rule cannot be said
    in iCalendar terms (an unknown zone, a Julian-day rule, a change time outside 00:00..23:59) -- the caller writes UTC then."""
    r = rule_of(name)
    if not r:
        return None
    try:
        p = parse(r)
    except ValueError:
        return None

    def ofs(sec):
        sg = "+" if sec >= 0 else "-"
        sec = abs(sec)
        return "%s%02d%02d" % (sg, sec // 3600, (sec % 3600) // 60)

    out = ["BEGIN:VTIMEZONE", "TZID:" + name]
    if not p["dst"] or p["start"] is None:
        return out + ["BEGIN:STANDARD", "DTSTART:19700101T000000", "TZOFFSETFROM:" + ofs(p["stdOff"]),
                      "TZOFFSETTO:" + ofs(p["stdOff"]), "TZNAME:" + p["std"], "END:STANDARD", "END:VTIMEZONE"]
    days = ["SU", "MO", "TU", "WE", "TH", "FR", "SA"]
    for comp, part, frm, to, nm in (("DAYLIGHT", p["start"], p["stdOff"], p["dstOff"], p["dst"]),
                                    ("STANDARD", p["end"], p["dstOff"], p["stdOff"], p["std"])):
        kind, mo, wk, wd, t = part
        if kind != "M" or not (0 <= t < 86400):
            return None
        d0 = _day_of(part, 1970)
        out += ["BEGIN:" + comp, "DTSTART:1970%02d%02dT%02d%02d%02d" % (d0.month, d0.day, t // 3600, (t % 3600) // 60, t % 60),
                "RRULE:FREQ=YEARLY;BYMONTH=%d;BYDAY=%s%s" % (mo, "-1" if wk == 5 else str(wk), days[wd]),
                "TZOFFSETFROM:" + ofs(frm), "TZOFFSETTO:" + ofs(to), "TZNAME:" + nm, "END:" + comp]
    out.append("END:VTIMEZONE")
    return out

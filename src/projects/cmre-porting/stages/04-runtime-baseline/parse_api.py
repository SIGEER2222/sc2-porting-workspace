import json, sys
p = r'E:\Code\MyMod\SC2\sc2-porting-workspace\projects\cmre-porting\stages\04-runtime-baseline\api-snapshot.json'
d = json.load(open(p, encoding='utf-8-sig'))
print('=== UNITS ===')
for u in d['probe_units']:
    print('  {} x{}'.format(u['unit_type_id'], u['count']))
print('=== PRODUCERS ===')
for p in d['probe_producers']:
    print('  {} count={} trainable={}'.format(p['producer_type_id'], p['producer_count'], p['trainable']))
print('=== TECH ABILITIES ===')
for a in d['probe_tech']['abilities']:
    print('  {}'.format(a))
print('=== TECH UPGRADES ===')
for u in d['probe_tech']['upgrades']:
    print('  {}={}'.format(u['upgrade_id'], u['count']))

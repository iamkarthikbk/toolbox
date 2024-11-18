import re
old_line_pattern = r'([\-])\[\s+(\d+)\]core\s+\d:\s[0-9]\s(?P<addr>[0-9abcdefx]+)\s\((?P<instr>[0-9abcdefx]+)\)'
new_line_pattern = r'([\+])\[\s+(\d+)\]core\s+\d:\s[0-9]\s(?P<addr>[0-9abcdefx]+)\s\((?P<instr>[0-9abcdefx]+)\)'
diff = input('path to diff: ')
with open(diff) as the_file:
    all_lines = the_file.readlines()
all_old_matches = re.findall(old_line_pattern, "".join(all_lines))
all_new_matches = re.findall(new_line_pattern, "".join(all_lines))
latency_ch_dict = dict()
occurance_dict = dict()
for i in range(len(all_old_matches)):
    if (all_old_matches[i][2] != all_new_matches[i][2]):
        print("something went wrong in list ordering")
    try:
        latency_ch_dict[f'{all_old_matches[i][2]}-{all_old_matches[i][3]}'] += int(all_old_matches[i][1]) - int(all_new_matches[i][1])
        occurance_dict[f'{all_old_matches[i][2]}-{all_old_matches[i][3]}'] += 1
    except KeyError:
        latency_ch_dict[f'{all_old_matches[i][2]}-{all_old_matches[i][3]}'] = int(all_old_matches[i][1]) - int(all_new_matches[i][1])
        occurance_dict[f'{all_old_matches[i][2]}-{all_old_matches[i][3]}'] = 1
from pprint import pprint as pp
pp(latency_ch_dict)
pp(occurance_dict)
latency_ch_val_list = list(latency_ch_dict.values())
oc_val_list = list(occurance_dict.values())
lcvl = latency_ch_val_list
ocvl = oc_val_list
print(min(lcvl))
print(lcvl)
print(max(ocvl))
print(ocvl)
print(f'{"sane" if len(ocvl) == len(lcvl) else "insane"}')
culprits = [9]
for entry in culprits:
    print(f'pc: {list(latency_ch_dict.keys())[entry-1]},{list(occurance_dict.values())[entry-1]},{list(latency_ch_dict.values())[entry-1]}')

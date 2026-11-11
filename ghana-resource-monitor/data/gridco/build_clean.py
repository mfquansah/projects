"""Build the cleaned GRIDCo series from data/gridco_operating_indicators_2013_2025.csv.
Rule: keep every raw row in the raw file; this script picks ONE value per (year, metric) and records why."""
import csv, collections, sys
RAW='gridco_operating_indicators_2013_2025.csv'
rows=list(csv.DictReader(open(RAW,encoding='utf-8-sig')))
by=collections.defaultdict(list)
for r in rows: by[(int(r['year']),r['metric'])].append(r)

# Manual decisions where the raw file has conflicts: (year,metric) -> (value to choose, confidence, method)
D={
(2019,'energy_transmitted'):('17887.0','high','Loss GWh / loss % = 17,898 GWh, matches the 2019 report (17,887); the 2020-report comparator (17,034) does not fit'),
(2020,'energy_transmitted'):('19716.59','high','Loss GWh / loss % = 19,711 GWh, matches the 2023-report series (19,716.59); the 2020 report headline (18,819) does not fit'),
(2021,'energy_transmitted'):('21466.0','high','Loss GWh / 5.01% = 21,477 GWh, matches 21,466; "2022" comparator label in the source is a typo for 2021'),
(2022,'energy_transmitted'):('22478.46','high','Loss GWh / loss % = 22,488 GWh, matches the 2022 report and the 2023 report p26 series; the 21,545 comparator does not fit'),
(2021,'transmission_losses'):('5.01','high','5.01% x 21,466 GWh = 1,076 GWh, which equals the audited loss volume; 5.15% does not'),
(2020,'system_peak_demand'):('3090','high','Chart value read from the 2021 report p20 and the 2025 report p26 series; both agree'),
(2013,'energy_transmitted'):('12930.0','medium','2013 report states 12.93 TWh transmitted; no loss GWh available to cross-check'),
(2024,'energy_transmitted'):('23692.0','low','Published headline, and the 2025 growth of 9.15% is computed from it. But the same report says "over 24,600" and loss GWh / 3.8% implies about 25,000. Unresolved'),
(2025,'energy_transmitted'):('25860.0','low','Published headline. Loss GWh (1,082) / 4.02% implies about 26,900, so the loss volume and the energy total may use different scopes. Unresolved'),
(2024,'transmission_losses'):('3.8','medium','Rounded chart label; do not infer more precision'),
(2014,'system_availability'):('99.79','low','Same-year narrative used; the 2016 report restates 99.17. Definitions may differ between reports'),
(2018,'system_availability'):('99.48','low','Same-year narrative used; the 2021 report restates 99.85. Definitions may differ'),
(2020,'system_availability'):('99.15','low','Same-year narrative used; the 2021 and 2024 charts show 99.69. Definitions may differ'),
(2021,'system_availability'):('99.22','low','Same-year narrative used; the chart on p20 of the same report shows 98.89'),
}
out=[]; log=[]
for (y,m),rs in sorted(by.items()):
    if (y,m) in D:
        val,conf,method=D[(y,m)]
        ch=[r for r in rs if r['value']==val] or [r for r in rs if abs(float(r['value'] or 0)-float(val))<1e-6]
        c=ch[0]
        rej=[f"{r['value']} ({r['source_report_year']} report p{r['pdf_page']})" for r in rs if r is not c and r['value']!='']
        out.append(dict(year=y,metric=m,value=val,unit=c['unit'],confidence=conf,source_file=c['source_file'],pdf_page=c['pdf_page'],method=method,rejected_values='; '.join(rej)))
        log.append((y,m,val,conf,'; '.join(rej),method))
        continue
    good=[r for r in rs if r['status'] in('reported','alternative_scope') and r['value']!='']
    if not good:
        out.append(dict(year=y,metric=m,value='',unit=rs[0]['unit'],confidence='none',source_file='',pdf_page='',method='Left blank: '+rs[0]['notes'],rejected_values='')); log.append((y,m,'','none','',rs[0]['notes'])); continue
    c=good[0]
    out.append(dict(year=y,metric=m,value=c['value'],unit=c['unit'],confidence='high' if c['status']=='reported' else 'medium',source_file=c['source_file'],pdf_page=c['pdf_page'],method='Single reported value, no conflict' if c['status']=='reported' else 'Different scope: '+c['notes'],rejected_values=''))
w=csv.DictWriter(open('clean/gridco_clean_2013_2025.csv','w',newline=''),fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
w=csv.writer(open('clean/gridco_decisions.csv','w',newline='')); w.writerow(['year','metric','chosen','confidence','rejected','why']); w.writerows(log)
print(len(out),'rows;',len(log),'decisions')

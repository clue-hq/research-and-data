# WVI-4 / 04: Research-paper register for anonymous-visitor identification

Date: 2026-10-03. Author: research agent (read-only literature sweep). Status: reference material, not a plan.

## 0. Scope, method and conventions

**Question.** What does the published record (peer-reviewed papers, measurement studies, serious industry audits, patents) say about every known way to turn an anonymous website visit into a company and then a person, how accurate each way is, and what data each needs?

**Already covered in WVI-2, not repeated here:** Zimmeck et al. cross-device tracking (USENIX Security 2017, F1 = 0.91 mobile-to-desktop from IP + history), the ICDM 2015 / CIKM cross-device challenges, Fingerprint's accuracy definitions, Prefix2Org (IMC 2025), ASdb (IMC 2021), Linnaeus AS classification, UID2 normalisation, Splink / Fellegi-Sunter. This register goes beyond those.

**Method.** Each entry below was located and opened (abstract or full text) during this sweep. Numbers are quoted from the paper's own abstract or body unless marked otherwise. Where only a title-level record could be confirmed, the entry says so and gives no numbers. Nothing here is invented; if a number is not given, it was not verified.

**Evidence grades used in each entry.**
- **[PR]** peer-reviewed academic paper.
- **[IND]** industry audit or white paper with a stated method and ground truth (e.g. Truthset/CIMM). Useful, not peer-reviewed.
- **[VEN]** vendor claim or vendor blog. Treated as a claim, not evidence.
- **[PAT]** patent. Describes a method a company filed; says nothing about whether it works or is still used.

**Legal/ethical tag.** Several items below are *attacks* (cross-site leaks, cache side channels, pre-submit form exfiltration, exploiting ad-platform custom audiences). They are in the register because (a) they bound what is technically possible and (b) some of the identity data sold to visitor-ID vendors originates in practices like these. Items tagged **DO NOT BUILD** are not candidate techniques for Clue.

---

## 1. How identity graphs are built, and how accurate they are

### 1.1 Venkatadri et al., "Privacy Risks with Facebook's PII-based Targeting: Auditing a Data Broker's Advertising Interface" [PR] DO NOT BUILD
- Citation: G. Venkatadri, A. Andreou, Y. Liu, A. Mislove, K. P. Gummadi, P. Loiseau, O. Goga. IEEE S&P 2018, pp. 89-107.
- Link: https://mislove.org/publications/PII-Oakland.pdf
- Summary: Shows that Facebook's custom-audience feature is a PII linking oracle. By uploading lists of PII and reading audience-size estimates, an adversary can infer a user's phone number from their email, test whether a specific person visited a site carrying a Facebook pixel, and de-anonymise *all* visitors to a pixel-tagged page by inferring their phone numbers digit by digit. Field test on 22 volunteers: phone numbers recovered for 11 of 14 in Boston and 8 of 8 in France, each in under 20 minutes once the reusable digit lists (1M to 10M numbers each) had been uploaded. Facebook subsequently changed the interface.
- What Clue can use: The proof that an ad platform with a pixel plus a PII graph *is* a visitor de-anonymiser. Clue must not use such side channels; but it explains why platforms throttle audience-size APIs and why any "LinkedIn/Facebook matched audience" route will only ever return aggregates.

### 1.2 Venkatadri et al., "Auditing Offline Data Brokers via Facebook's Advertising Platform" [PR]
- Citation: G. Venkatadri, P. Sapiezynski, E. M. Redmiles, A. Mislove, O. Goga, M. L. Mazurek, K. P. Gummadi. WWW 2019.
- Link: https://www.ccs.neu.edu/home/amislove/publications/DataBrokers-WWW.pdf
- Summary: Uses Facebook's partner-category targeting (six brokers, seven countries) to see broker data attached to accounts. Over 90% of US Facebook accounts were linked to broker data. Controlled ads to 183 US volunteers found at least 40% of broker-sourced attributes "not at all accurate"; financial attributes were worse (e.g. investment attributes 56% "not at all accurate").
- What Clue can use: Coverage and accuracy are decoupled. A broker graph can link >90% of people and still be wrong on 40% of attributes. Any purchased enrichment must be validated per attribute, not trusted because the match rate is high.

### 1.3 Neumann, Tucker, Whitfield, "Frontiers: How Effective Is Third-Party Consumer Profiling? Evidence from Field Studies" [PR]
- Citation: N. Neumann, C. Tucker, T. Whitfield. Marketing Science 38(6):918-926, 2019.
- Link: https://ide.mit.edu/wp-content/uploads/2022/02/c.tucker.pdf (working-paper copy); https://ideas.repec.org/a/inm/ormksc/v38y2019i6p918-926.html
- Summary: Three field tests over 90+ third-party audiences from 19 brokers, validated with Nielsen DAR panel and self-report. Black-box profiles improved hitting a single desired attribute by 0% to 77% over random; in one test the ad reached the right age/gender segment 59% of the time, and gender was on average about as good as chance in another; interest segments scored 72.8% to 87.4%.
- What Clue can use: Sets an external baseline for "how often is a bought segment right": barely better than random for demographics. Person-level claims built on broker demographics need an independent check.

### 1.4 Neumann, Tucker, Kaplan, Mislove, Sapiezynski, "Data Deserts and Black Boxes: The Impact of Socio-Economic Status on Consumer Profiling" [PR]
- Citation: Management Science 70(11), 2024. DOI 10.1287/mnsc.2023.4979.
- Link: https://www.ccs.neu.edu/home/amislove/publications/Deserts-ManageSci24.pdf
- Summary: Five field tests, 15 brokers. Who is profiled, and how accurately, depends mostly on the person, not the vendor: affluent, college-educated, white-collar people are profiled more often and more accurately; lower-income people sit in "data deserts" because their digital footprint (devices, time online) is narrower. Vendor method explains almost none of the accuracy variance; vendor partnerships explain who is covered.
- What Clue can use: B2B buyers are mostly in the well-covered population, so coverage will look better than consumer benchmarks. Accuracy is driven by footprint, so the right per-visitor confidence feature is "how much independent evidence do we have about this person", not "which vendor said so".

### 1.5 Truthset and CIMM, "Household Identity Accuracy Project" (email-to-postal) [IND]
- Citation: Truthset / Coalition for Innovative Media Measurement, Q3 2023 (released 2024).
- Link: https://cimm-us.org/wp-content/uploads/2024/04/Truthset-Household-Identity-Accuracy-Project_October-2023.pdf ; press summary https://www.tvrev.com/news/household-identity-study-reveals-marketing-waste-truthset-improvement
- Summary: Scored HEM-to-postal linkages from 15+ large US identity providers (790M+ unique hashed emails, 1.2B+ HEM:postal pairs, 130M+ postals) against 20M+ self-reported panel and e-commerce records (2015-2023). Average accuracy 51%, ranging 32% to 69% by provider. Each email linked on average to 1.6 postals; each postal to 9.1 emails. Demographic attributes attached via email carry 20% to 60% error depending on attribute.
- What Clue can use: The single best public number for how often a deterministic-looking identity link (hashed email to household) is actually right: about half. Any graph Clue licenses should come with per-link confidence, and Clue should keep only links corroborated by a second source.

### 1.6 Truthset, CIMM and Go Addressable, "The Challenges of Using IP Address for Audience Identification and Measurement" [IND]
- Citation: Truthset / CIMM / Go Addressable, 5 Nov 2025.
- Link: https://cimm-us.org/wp-content/uploads/2025/11/CIMM-_-GoAddressable-_-Truthset-Challenges-of-Using-IP-Address-for-Audience-Identification-and-Measurement-November-2025.pdf
- Summary: Six identity-data providers (938M IP-to-postal pairs, 5.6B IP-to-email pairs, 247M IPs, 1B emails) were scored against ground truth from two ISPs and one vMVPD that know which household each router IP was assigned to (Dec 2024 to Feb 2025, IPv4). IP-to-postal linkages were right 13% of the time on average (providers ranged 4% to 18%); IP-to-email 16% (7% to 30%). Providers agreed with each other on only 6.4% of IP-to-postal and 2.8% of IP-to-email links; 93% of links were unique to one provider. Providers carried 3.2 IPs per postal versus about 1.2 in ISP truth. IPv6 was under-represented by 72%. Accuracy moved day to day and by state (5% to 17%).
- What Clue can use: This is the most important number in the register for person-level visitor ID. **A purchased IP-to-person link is wrong roughly five times out of six.** Any "IP + UA resolves to this named person" product that leans on third-party IP-to-email graphs inherits that error unless it has its own corroboration. It also says IPv6 is a gap in commercial graphs, so a first-party IPv6 observation can be more informative than the vendor graph.

### 1.7 Nielsen validations of Tapad and Drawbridge device graphs [VEN]
- Citation: Vendor-commissioned Nielsen studies reported in trade press, 2014-2016.
- Links: https://adtechdaily.com/2014/12/15/nielsen-study-finds-tapads-device-connections-91-2-percent-accurate/ ; https://www.webwire.com/ViewPressRel.asp?aId=197231 ; context https://www.adexchanger.com/data-exchanges/2016-edition-marketers-guide-cross-device-identity/
- Summary: Tapad's device connections were reported 91.2% "accurate" over a two-week Nielsen panel comparison; Drawbridge 97.3% over one month. AdExchanger notes that "accuracy" here counts correct non-matches as well as correct matches, so it is not precision; sophisticated buyers were sceptical.
- What Clue can use: A cautionary example of metric choice. Clue's own reporting must use precision and recall at a stated threshold, never "accuracy" over a mostly-negative pair space.

### 1.8 Cotta, Hu, Jiang, Liao, "Off-Policy Evaluation of Probabilistic Identity Data in Lookalike Modeling" [PR]
- Citation: WSDM 2019. arXiv 1901.05560.
- Link: https://arxiv.org/abs/1901.05560
- Summary: Industry-affiliated authors (a "Randy Cotta" is also listed as an inventor on the Drawbridge device-grouping patent in section 8.5; whether this is the same person was not verified). Using off-policy evaluation on Sep-Dec 2017 data, adding probabilistic identity links lifted lookalike conversion rates about 70% on average and 4x to 32x for short-lived identifiers with little history. Flags finite-sample bias when evaluating rare-event metrics.
- What Clue can use: Probabilistic linking pays off most for identifiers with thin history, which is exactly the first-visit anonymous visitor. Also a method note: evaluate with off-policy estimators and watch small-sample bias.

### 1.9 Brookman, Rouge, Alva, Yeung, "Cross-Device Tracking: Measurement and Disclosures" [PR]
- Citation: PoPETs 2017(2):133-148. FTC Office of Technology Research and Investigation.
- Link: https://petsymposium.org/popets/2017/popets-2017-0020.php
- Summary: Reviewed 100 popular sites on multiple devices to see what data flows enable cross-device linking: the same third parties on different devices, hashed or plaintext login identifiers sent to third parties, cookie syncing. Policies rarely disclosed cross-device practices.
- What Clue can use: A regulator's map of the deterministic linking signals (login identifiers reaching third parties) that the ecosystem uses. Clue's own login and form events are the clean, first-party version of the same signal.

### 1.10 Wang, Zhou, Li, Cao, Gong, "GraphTrack: A Graph-based Cross-Device Tracking Framework" [PR]
- Citation: ACM AsiaCCS 2022. arXiv 2203.06833.
- Link: https://arxiv.org/abs/2203.06833
- Summary: Models IPs, domains and devices as a graph, captures latent IP-IP and domain-domain correlations, and scores device similarity with random walk with restart. Works without labelled device pairs and is robust to noisy history-to-device attribution. Evaluated on two real datasets.
- What Clue can use: A label-free way to cluster Clue's own cookies/devices by shared IPs and page co-visitation, useful before Clue has many deterministic labels.

### 1.11 Papadopoulos, Kourtellis, Markatos, "Cookie Synchronization: Everything You Always Wanted to Know But Were Afraid to Ask" [PR]
- Citation: WWW 2019. arXiv 1805.10505.
- Link: https://arxiv.org/abs/1805.10505
- Summary: Year-long logs from 850 real mobile users. 97% were exposed to cookie syncing, most within their first week; the median user ID leaked to 3.5 domains; syncing multiplied the number of domains tracking a user by 6.75.
- What Clue can use: Explains how a single deterministic identification event (one login, one email click) propagates across the ad ecosystem. Clue should expect vendor graphs to be built this way and should not rely on third-party cookies, which are blocked in Safari and Firefox.

### 1.12 Acar et al., "The Web Never Forgets: Persistent Tracking Mechanisms in the Wild" [PR]
- Citation: G. Acar, C. Eubank, S. Englehardt, M. Juarez, A. Narayanan, C. Diaz. ACM CCS 2014.
- Link: https://dl.acm.org/doi/10.1145/2660267.2660347
- Summary: First large measurement of canvas fingerprinting, evercookies and cookie syncing in the wild; found canvas fingerprinting on about 5% of the top 100K sites and showed respawning and syncing combine to defeat cookie clearing.
- What Clue can use: Historical baseline for persistence techniques; most have since been mitigated by browser storage partitioning, so Clue should not design around them.

### 1.13 Smith et al., "Bridging the Gap: A Longitudinal Analysis of Extended Identifiers in the Post-Cookie Era" [PR-preprint]
- Citation: M. Smith, R. Grossman, K. Franaszek, A. Torres-Aguero, P. Sen, C. Borcea, Y. Chen. arXiv 2609.02069, 2026.
- Link: https://arxiv.org/abs/2609.02069
- Summary: 41 months of header-bidding traffic (145M+ requests, 616,539 sites, 6 SSPs, 18 extended-identifier (EID) providers, which include hashed-email-based IDs). By May 2025, 83.76% of studied sites sent EIDs; 18 providers carried 99.42% of EIDs; 12 create persistent identifiers that follow users across sites, devices and months; 16 transmit EIDs on EU sites without consent.
- What Clue can use: Hashed-email-derived IDs are now the dominant cross-site identifier in programmatic advertising. A visitor who has authenticated anywhere in that ecosystem is likely already resolved by someone; Clue's question is whether it can lawfully access that resolution (e.g. via a licensed partner) rather than rebuild it.

### 1.14 Randall et al., "Measuring UID Smuggling in the Wild" [PR]
- Citation: A. Randall, P. Snyder, A. Ukani, A. C. Snoeren, G. M. Voelker, S. Savage, A. Schulman. IMC 2022.
- Link: https://arxiv.org/abs/2203.10188
- Summary: Trackers evade storage partitioning by putting user IDs in navigation URLs (link decoration). CrumbCruncher found UID smuggling on more than 8% of navigations.
- What Clue can use: Click IDs and decorated links (including email-campaign links Clue itself sends) are a legitimate first-party way to carry identity from an email into a site visit. Clue's own outbound emails can carry a signed, first-party token.

### 1.15 Chen, Ilia, Polychronakis, Kapravelos, "Cookie Swap Party: Abusing First-Party Cookies for Web Tracking" [PR]
- Citation: WWW 2021.
- Link: https://www.kapravelos.com/publications/cookieparty-www21.pdf
- Summary: Dynamic data-flow tracking in Chromium over the Alexa top 10K shows third-party scripts setting first-party cookies and then exfiltrating them to other third parties, re-creating cross-site tracking even when third-party cookies are blocked.
- What Clue can use: Clue's snippet will run first-party; it must not share its first-party ID with other parties, or it becomes the behaviour this paper documents.

### 1.16 Dimova, Acar, Olejnik, Joosen, Van Goethem, "The CNAME of the Game: Large-scale Analysis of DNS-based Tracking Evasion" [PR]
- Citation: PoPETs 2021(3):394-412.
- Link: https://bibbase.org/network/publication/dimova-acar-olejnik-joosen-vangoethem-thecnameofthegamelargescaleanalysisofdnsbasedtrackingevasion-2021
- Summary: Longitudinal study of trackers served from a customer subdomain via CNAME to bypass blocklists and gain first-party cookie context. (Abstract confirmed; specific counts not extracted in this sweep.)
- What Clue can use: A first-party collection endpoint on the customer's own subdomain improves data survival, but CNAME cloaking is now detected by Safari ITP and some blockers and attracts regulatory attention. Prefer a documented first-party proxy over a disguised one.

---

## 2. Email tracking, form leakage and hashed email as a cross-site key

### 2.1 Englehardt, Han, Narayanan, "I never signed up for this! Privacy implications of email tracking" [PR]
- Citation: PoPETs 2018(1). DOI 10.1515/popets-2018-0006.
- Link: https://petsymposium.org/popets/2018/popets-2018-0006.pdf ; code https://github.com/citp/email_tracking
- Summary: Corpus of commercial mailing-list emails from 902 senders. 85% embed third-party content, 70% contain known trackers. About 29% to 30% of emails leak the recipient's address (plaintext or hashed) to a third party when opened; 19% of senders leak at least once; 62% of the 100,963 leaks are intentional. When links are clicked, 11% of links leak the address to a third party and at least 35% of senders have such a link. Top recipients include Acxiom/LiveRamp, Conversant, LiveIntent, Neustar. Tracking-protection lists cut leaks by 87%.
- What Clue can use: Email opens and clicks are a primary feedstock of the commercial email-to-cookie graph (the identity-resolution patent in section 8.7 describes exactly this). For Clue, the clean version is: Clue's own outbound sequences carry a first-party token, so a click deterministically identifies the person on arrival. Opens are unreliable (Apple Mail Privacy Protection prefetches images; no measurement study of its effect was located in this sweep).

### 2.2 Hu, Peng, Wang, "Characterizing Pixel Tracking through the Lens of Disposable Email Services" [PR]
- Citation: IEEE S&P 2019. DOI 10.1109/SP.2019.00033.
- Link: https://gangw.cs.illinois.edu/tracking-sp19.pdf
- Summary: 2.3M emails from 210K sender domains via 7 disposable-email services. 24.6% contain at least one tracking link; about 50% of Alexa top-10K senders track. Tracking URLs carrying the recipient address in plaintext (200,682) are about as common as obfuscated ones (200,247); of obfuscations, MD5 is 91.7% and Base64 4.9%. Trackers hide pixels (548K invisible HTML pixels, 537K "remote" pixels that misdeclare their size). Top 10 trackers cover 31.8% of sender domains.
- What Clue can use: MD5 of a normalised email is still the de facto join key in email tracking, alongside SHA-256 in ad tech. Clue's normaliser should compute both, and treat either as personal data.

### 2.3 Xu, Hao, Sari, Wang, "Privacy Risk Assessment on Email Tracking" [PR]
- Citation: IEEE INFOCOM 2018.
- Link: https://users.eecs.northwestern.edu/~hxb0652/HaitaoXu_files/INFOCOM2018_1.pdf
- Summary: Independent contemporaneous study of email tracking techniques and the third parties involved. (Title and venue confirmed; numbers not extracted.)
- What Clue can use: Corroborates 2.1 and 2.2.

### 2.4 Senol, Acar, Humbert, Zuiderveen Borgesius, "Leaky Forms: A Study of Email and Password Exfiltration Before Form Submission" [PR] DO NOT BUILD
- Citation: USENIX Security 2022.
- Link: https://www.usenix.org/system/files/sec22-senol.pdf ; code https://github.com/leaky-forms/leaky-forms
- Summary: Crawled the top 100K sites from EU and US vantage points, filled email/password fields and did not submit. Emails were exfiltrated to tracking, marketing and analytics domains *before submission and without consent* on 1,844 sites (EU) and 2,950 sites (US); 41 receiving tracker domains were on no blocklist; 52 sites incidentally collected passwords via session-replay scripts. LiveRamp (rlcdn.com) collected MD5, SHA-1 and SHA-256 hashes on sites such as WebMD and Fox News; Taboola dominated in the EU; Yahoo's ConnectID endpoint and Neustar/LiveRamp received hashes relayed by other scripts; Facebook received emails or hashes on 21 EU sites, 17 via Automatic Advanced Matching.
- What Clue can use: Documents how commercial graphs acquire email-to-cookie links at scale, and that capturing a typed email before submit is the behaviour regulators and researchers flag. Clue's snippet should capture identity only on an explicit submit or login, with consent where required.

### 2.5 Starov, Gill, Nikiforakis, "Are You Sure You Want to Contact Us? Quantifying the Leakage of PII via Website Contact Forms" [PR]
- Citation: PoPETs 2016(1). DOI 10.1515/popets-2015-0028.
- Link: https://petsymposium.org/2016/files/papers/Are_You_Sure_You_Want_to_Contact_Us__Quantifying_the_Leakage_of_PII_via_Website_Contact_Forms.pdf
- Summary: Top 100K sites; contact forms found and submitted on 16,981 sites. 2.5% of forms accidentally leak PII via URL/Referer, and 6.1% (1,035) of submitted forms leak PII to third parties intentionally or accidentally; third-party scripts such as LeadLander's actively scrape email fields.
- What Clue can use: Old but direct evidence that B2B "contact us" pages were an early identity-capture surface for visitor-ID vendors. Clue's own form capture is legitimate first-party data; do not send it to other parties.

### 2.6 Dao, Fukuda, "Alternative to third-party cookies: investigating persistent PII leakage-based web tracking" [PR]
- Citation: H. Dao, K. Fukuda. CoNEXT 2021, pp. 223-229. DOI 10.1145/3485983.3494860.
- Link: https://dl.acm.org/doi/10.1145/3485983.3494860
- Summary: 42.3% of 307 popular shopping sites (Tranco top 10K) leak PII to third parties during authentication flows, enabling persistent, cross-browser, cross-device tracking keyed on PII.
- What Clue can use: Confirms that login flows are the anchor for "persistent PII-based identifiers". A logged-in customer portal is the strongest first-party identity event Clue's customers have.

### 2.7 Pham, Vo, Dao, Fukuda, "I Never Willingly Consented to This! Investigate PII Leakage via SSO Logins" [PR]
- Citation: IEEE Transactions on Privacy 2(2):67-78, 2025.
- Link: https://ieeexplore.ieee.org/document/10950125/
- Summary: During "Sign in with Google/Facebook" flows, PII moves across many domains in those ecosystems; 28.9% (Google) and 41.9% (Facebook) of third-party domains contacted during SSO login belong to advertising/tracking companies.
- What Clue can use: Social login is an identity event that third parties already see. If a Clue customer offers SSO, the resulting email is first-party data for that customer; Clue should not try to observe other sites' SSO.

### 2.8 Bekos, Papadopoulos, Kourtellis, Polychronakis, "PIIxel Leaks: Passive Identification of PII Leakage through Meta Pixel" [PR]
- Citation: ACM CCS 2025. DOI 10.1145/3719027.3765113.
- Link: https://dl.acm.org/doi/10.1145/3719027.3765113
- Summary: Reads Meta Pixel configuration statically across the top 1M sites: 12.2% leak at least one PII item to Meta (email, phone, plus age, gender, geography), and the pixel can reconstruct full-URL browsing journeys.
- What Clue can use: Meta (and similarly LinkedIn's Insight Tag) already performs person-level resolution of visitors for advertising, but returns only aggregates to the site owner. That is the platform reality Clue competes with.

### 2.9 Kieserman, Andreou, Geeng, Lauinger, McCoy, "Tracker Installations Are Not Created Equal: Understanding Tracker Configuration of Form Data Collection" [PR]
- Citation: PoPETs 2025. arXiv 2506.16891.
- Link: https://arxiv.org/abs/2506.16891
- Summary: 40,150 sites. Google trackers on 72.6%, Meta on 28.2%; configured for form-data collection on 11.6% (Google) versus 62.3% (Meta) of installs; some finance and health sites likely violate the platforms' own policies.
- What Clue can use: Shows where hashed form data is already flowing. Also a design warning: a "collect form fields automatically" default is the pattern that draws regulator and researcher attention.

### 2.10 Vlachogiannakis et al., "I Know What You Bought Last Summer: Investigating User Data Leakage in E-Commerce Platforms" [PR]
- Citation: SECRYPT 2025. arXiv 2504.13212.
- Link: https://arxiv.org/abs/2504.13212
- Summary: Nearly 30% of sampled e-shops disclosed personal information to third parties (plaintext, MD5, SHA-256, URL- and Base64-encoded), notably to Facebook.
- What Clue can use: Same lesson as 2.6; confirms the encodings to normalise for.

### 2.11 Acar, Englehardt, Narayanan, "Four cents to deanonymize: Companies reverse hashed email addresses" [IND, academic blog]
- Citation: Freedom to Tinker / Princeton CITP blog, 9 Apr 2018.
- Link: https://blog.citp.princeton.edu/2018/04/09/four-cents-to-deanonymize-companies-reverse-hashed-email-addresses/
- Summary: Commercial services reverse hashed emails: one advertised $0.04 per email with a claimed 70% recovery rate; another reversed nearly 3M addresses for a client. Hashing every known address costs almost nothing, so an unsalted hash is a pseudonymous identifier, not anonymisation.
- What Clue can use: Treat SHA-256/MD5 of an email as personal data in storage, logs and contracts.

### 2.12 FTC Office of Technology, "No, hashing still doesn't make your data anonymous" [IND, regulator]
- Citation: US Federal Trade Commission, 24 Jul 2024.
- Link: https://www.ftc.gov/policy/advocacy-research/tech-at-ftc/2024/07/no-hashing-still-doesnt-make-your-data-anonymous
- Summary: Hashed identifiers are persistent unique identifiers; the FTC cites enforcement against Nomi (2015), BetterHelp, Premom and InMarket where hashed data still enabled identification.
- What Clue can use: Regulatory position to quote in Clue's DPA and data-handling design.

---

## 3. IP address as an identifier

### 3.1 Mishra, Laperdrix, Vastel, Rudametkin, Rouvoy, Lopatka, "Don't Count Me Out: On the Relevance of IP Address in the Tracking Ecosystem" [PR]
- Citation: WWW 2020. DOI 10.1145/3366423.3380161.
- Link: https://doi.org/10.1145/3366423.3380161 ; https://hal.science/hal-02435622/
- Summary: 34,488 public IPs from 2,230 users over 111 days. 87% of participants retained at least one IP for more than a month; 45% of ISPs let a device keep the same IP more than 30 days. Users cycle among a set of IPs, and the cycles reveal behaviour and mobility (home, work, travel).
- What Clue can use: A residential IP is a weeks-long pseudonym, not a session-long one. Clue can treat (IP, time window) as a household key with a decay of roughly a month, and use the *set* of IPs a cookie has used (home + office) as a strong linking feature.

### 3.2 Padmanabhan, Dhamdhere, Aben, claffy, Spring, "Reasons Dynamic Addresses Change" [PR]
- Citation: IMC 2016.
- Link: https://www.caida.org/catalog/papers/2016_reasons_dynamic_addresses_change/reasons_dynamic_addresses_change.pdf
- Summary: 3,038 RIPE Atlas probes in 929 ASes, all of 2015. 20 ISPs renumber on a fixed period (often a multiple of 24 hours; e.g. DTAG daily, Orange weekly); others (Verizon, Liberty Global) show no periodicity. In North America, addresses spent more than half their time in durations longer than 50 days. Address changes correlate with CPE outages; almost half of changes moved to a different BGP prefix.
- What Clue can use: IP stability is per-ISP. Clue should learn an expected lease length per ASN (from its own data) and down-weight IP evidence on ISPs known to renumber daily. Do not assume a new IP is still in the same /24.

### 3.3 Padmanabhan, Rula, Richter, Strowes, Dainotti, "DynamIPs: Analyzing Address Assignment Practices in IPv4 and IPv6" [PR]
- Citation: CoNEXT 2020. DOI 10.1145/3386367.3431314.
- Link: https://dl.acm.org/doi/abs/10.1145/3386367.3431314
- Summary: Measures how long ISPs keep assigning the same IPv4 address and IPv6 delegated prefix to a subscriber. (Title, authors and venue confirmed; numbers not extracted in this sweep.)
- What Clue can use: The IPv6 counterpart to 3.2; read before using a /56 or /64 as a household key.

### 3.4 Cai, Heidemann, "Understanding Block-level Address Usage in the Visible Internet" [PR]
- Citation: ACM SIGCOMM 2010. DOI 10.1145/1851182.1851196.
- Link: https://dl.acm.org/doi/10.1145/1851182.1851196
- Summary: From ICMP probing of 1% of IPv4 space, 61% of probed addresses sit in consistent blocks of 64+ neighbours; nearly 40% of /24 blocks look dynamically allocated (over 80% in China, under 30% in the US).
- What Clue can use: Block-level classification (static vs dynamic, business vs residential) is feasible from activity patterns. Supports a Clue feature "is this /24 behaving like an office block".

### 3.5 Richter et al., "A Multi-perspective Analysis of Carrier-Grade NAT Deployment" [PR]
- Citation: P. Richter, F. Wohlfart, N. Vallina-Rodriguez, M. Allman, R. Bush, A. Feldmann, C. Kreibich, N. Weaver, V. Paxson. IMC 2016.
- Link: https://www.icir.org/christian/publications/2016-imc-cgnat.pdf
- Summary: BitTorrent DHT crawl (21M+ peers, ~19K ASes) plus Netalyzr. CGN present in 17% to 18% of "eyeball" ASes and in more than 90% of cellular ASes (94% of cellular sessions showed a translated address).
- What Clue can use: **A mobile-carrier IP identifies nobody.** Clue should classify cellular ASNs and zero out IP-based person evidence for them; company inference from a cellular IP is also near useless.

### 3.6 Livadariu, Benson, Elmokashfi, Dhamdhere, Dainotti, "Inferring Carrier-Grade NAT Deployment in the Wild" [PR]
- Citation: IEEE INFOCOM 2018.
- Link: https://dl.acm.org/doi/10.1109/INFOCOM.2018.8486223
- Summary: Independent CGN detection method and census. (Title and venue confirmed; numbers not extracted.)
- What Clue can use: Second source for a CGN/ASN exclusion list.

### 3.7 Plonka, Berger, "Temporal and Spatial Classification of Active IPv6 Addresses" [PR]
- Citation: IMC 2015.
- Link: https://conferences2.sigcomm.org/imc/2015/papers/p509.pdf
- Summary: A year of CDN logs. Because of privacy extensions, the vast majority of IPv6 client addresses are used for 24 hours or less and never again; stability lives at the prefix level, so addresses should be classified temporally (by activity lifetime) and spatially (by density within prefixes).
- What Clue can use: Never key on a full IPv6 address. Key on the delegated prefix (/56 or /64 depending on ISP) and learn per-ISP prefix stability.

### 3.8 Saidi, Gasser, Smaragdakis, "One Bad Apple Can Spoil Your IPv6 Privacy" [PR]
- Citation: ACM SIGCOMM CCR 52(2), 2022. arXiv 2203.08946.
- Link: https://arxiv.org/abs/2203.08946
- Summary: Flow data from a large European ISP: about 19% of end-user prefixes host at least one device that embeds its MAC (EUI-64) in its IPv6 address, mostly IoT. That single device lets any observer follow the household across prefix rotations, defeating both ISP rotation and privacy extensions on the other devices.
- What Clue can use: Clue only sees visitors' browsers, which use privacy extensions, so this is mostly not available to a website. It shows why household continuity across IPv6 rotation is possible for ISPs and large platforms but not for a site owner.

### 3.9 Rye, Beverly, "IPvSeeYou: Exploiting Leaked Identifiers in IPv6 for Street-Level Geolocation" [PR] DO NOT BUILD
- Citation: IEEE S&P 2023. arXiv 2208.06767.
- Link: https://erikrye.com/assets/files/rye-ipvseeyou-sp23.pdf
- Summary: Recovers router WAN MACs from EUI-64 IPv6 addresses via active probing, maps them to WiFi BSSIDs in wardriving databases, and geolocates the IPv6 prefixes of more than 12M routers in 146 countries with a median error of 39 m.
- What Clue can use: Bounds what IPv6 can reveal about a home's physical location. Not a technique Clue should use; relevant to privacy reviews of storing raw IPv6 prefixes.

### 3.10 Sattler, Aulbach, Zirngibl, Carle, "Towards a Tectonic Traffic Shift? Investigating Apple's New Relay Network" [PR]
- Citation: IMC 2022. DOI 10.1145/3517745.3561426.
- Link: https://www.net.in.tum.de/fileadmin/bibtex/publications/papers/sattler2022privaterelay.pdf
- Summary: Found 1,586 IPv4 and 1,575 IPv6 ingress relay addresses (ingress grew 20% Jan to Apr 2022); verified that egress addresses rotate; 5.3% of RIPE Atlas probes used resolvers blocking the relay.
- What Clue can use: Visitors behind iCloud Private Relay are unresolvable by IP. Clue should flag relay egress traffic (Apple publishes egress ranges in its operator documentation) and route those sessions to non-IP evidence only.

### 3.11 Mi et al., "Resident Evil: Understanding Residential IP Proxy as a Dark Service" [PR]
- Citation: X. Mi, X. Feng, X. Liao, et al. IEEE S&P 2019, pp. 1185-1201. DOI 10.1109/SP.2019.00011.
- Link: https://conferences.computer.org/sp/pdfs/sp/2019/ResidentEvilUnderstandingResidentialIPProxyasa.pdf
- Summary: Infiltrated residential-proxy services and found about 6M residential IPs in 230+ countries and 52K+ ISPs being used to relay others' traffic.
- What Clue can use: A "residential" IP visiting a B2B site may be a scraper or bot borrowing someone's home connection. Clue needs bot filtering before identity resolution, or it will "identify" the proxy's unwitting host.

### 3.12 Feldmann et al., "The Lockdown Effect: Implications of the COVID-19 Pandemic on Internet Traffic" [PR]
- Citation: A. Feldmann, O. Gasser, F. Lichtblau, E. Pujol, I. Poese, C. Dietzel, D. Wagner, M. Wichtlhuber, J. Tapiador, N. Vallina-Rodriguez, O. Hohlfeld, G. Smaragdakis. IMC 2020.
- Link: https://arxiv.org/pdf/2008.10959
- Summary: ISP, IXP and campus vantage points show traffic for remote working, education and entertainment shifting onto residential networks during lockdowns, with work-hour patterns appearing on home connections. (Qualitative summary from abstract.)
- What Clue can use: The academic evidence that business browsing moved onto residential IPs, which is the root cause of reverse-IP decay (section 7).

### 3.13 Gharaibeh et al., "A Look at Router Geolocation in Public and Commercial Databases" and Poese et al., "IP Geolocation Databases: Unreliable?" [PR]
- Citations: M. Gharaibeh, A. Shah, B. Huffaker, H. Zhang, R. Ensafi, C. Papadopoulos, IMC 2017; I. Poese, S. Uhlig, M. A. Kaafar, B. Donnet, B. Gueye, ACM CCR 41(2), 2011.
- Links: https://www.caida.org/catalog/papers/2017_look_at_router_geolocation/look_at_router_geolocation.pdf ; https://dl.acm.org/doi/10.1145/1971162.1971171
- Summary: Gharaibeh et al. build a 16,586-interface ground truth and find public and commercial databases unreliable for geolocating routers at country and city level. Poese et al. found databases usable at country level but not trustworthy at city level.
- What Clue can use: City-level IP geolocation is weak evidence. Use it only as a soft consistency check (e.g. "visitor city matches person's LinkedIn city"), never as a deciding feature.

### 3.14 Viant (Vindico) patent: household identification from IP [PAT]
- See section 8.8. Gives an explicit industry recipe: residential-ISP check, activity threshold to exclude businesses, and an IP-assignment age threshold (example 45 days) before an IP is trusted as a household key.

---

## 4. Browser fingerprinting: uniqueness, stability, and use for re-identification

### 4.1 Eckersley, "How Unique Is Your Web Browser?" [PR]
- Citation: P. Eckersley. PETS 2010.
- Link: https://coveryourtracks.eff.org/static/browser-uniqueness.pdf
- Summary: 470,161 Panopticlick fingerprints from privacy-aware visitors: 83.6% unique, at least 18.1 bits of entropy; 94.2% unique when Flash or Java was present. A simple heuristic re-linked changed fingerprints correctly about 99% of the time.
- What Clue can use: Historical upper bound on a self-selected, plugin-era population. Do not reuse its numbers for 2026 traffic.

### 4.2 Laperdrix, Rudametkin, Baudry, "Beauty and the Beast: Diverting Modern Web Browsers to Build Unique Browser Fingerprints" (AmIUnique) [PR]
- Citation: IEEE S&P 2016. DOI 10.1109/SP.2016.57.
- Link: https://plaperdr.github.io/
- Summary: AmIUnique dataset; 89.4% of fingerprints unique (about 90% desktop, 81% mobile as later summarised by Pugliese et al.); canvas and new APIs replaced plugins as the most discriminating attributes.
- What Clue can use: Canvas/WebGL/audio features are where entropy lives; also where browsers now add noise (section 4.9).

### 4.3 Gomez-Boix, Laperdrix, Baudry, "Hiding in the Crowd: an Analysis of the Effectiveness of Browser Fingerprinting at Large Scale" [PR]
- Citation: WWW 2018. DOI 10.1145/3178876.3186097.
- Link: https://dl.acm.org/doi/fullHtml/10.1145/3178876.3186097
- Summary: 2,067,942 fingerprints from a top-15 French site (general population): only 33.6% unique (18.5% on mobile). Non-unique fingerprints are fragile and become unique if a feature changes.
- What Clue can use: **The realistic number for a general audience is about one third unique, far lower on mobile.** A fingerprint is a weak person identifier on its own; useful only combined with IP and time.

### 4.4 Andriamilanto, Allard, Le Guelvouit, Garel, "A Large-scale Empirical Analysis of Browser Fingerprints Properties for Web Authentication" [PR]
- Citation: ACM Transactions on the Web 16(1), 2022. arXiv 2006.09511.
- Link: https://arxiv.org/abs/2006.09511
- Summary: 4,145,408 fingerprints (216 attributes) from 1,989,365 browsers: more than 81.3% of fingerprints shared by a single browser; on average 91% of attributes unchanged between observations even about six months apart.
- What Clue can use: With a rich attribute set and a large population, fingerprints are distinctive and mostly stable. Shows the ceiling if Clue collected many attributes (which carries consent implications under ePrivacy).

### 4.5 Vastel, Laperdrix, Rudametkin, Rouvoy, "FP-STALKER: Tracking Browser Fingerprint Evolutions" [PR]
- Citation: IEEE S&P 2018.
- Link: https://www.computer.org/csdl/proceedings-article/sp/2018/435301a728/12OmNAtK4bC ; arXiv 1802.03207
- Summary: Two years of fingerprints from 1,905 volunteers. 50% of browser instances changed fingerprint within 5 days, 80% within 10 days; the hybrid (rules + random forest) linker kept a browser tracked for 51 days on average, 36 days longer than the previous best.
- What Clue can use: Fingerprints must be linked with an evolution-aware matcher, not exact match. The linker design (rules for impossible changes, ML for similarity) is a template for Clue's first-party re-identification of returning cookie-less visitors.

### 4.6 Li, Cao, "Who Touched My Browser Fingerprint? A Large-scale Measurement Study and Classification of Fingerprint Dynamics" [PR]
- Citation: IMC 2020. DOI 10.1145/3419394.3423614.
- Link: https://yinzhicao.org/fpmeasurement/imc20.pdf
- Summary: Millions of fingerprints from a real website; classifies changes into causes (browser/OS updates, user actions, environment) and shows that the state-of-the-art evolution-aware linker performs poorly in F1 and speed at real-world scale.
- What Clue can use: Lab results (4.5) overstate linking accuracy at scale; Clue should measure its own linker on its own traffic.

### 4.7 Pugliese, Riess, Gassmann, Benenson, "Long-Term Observation on Browser Fingerprinting: Users' Trackability and Perspective" [PR]
- Citation: PoPETs 2020(2). DOI 10.2478/popets-2020-0041.
- Link: https://petsymposium.org/popets/2020/popets-2020-0041.pdf
- Summary: 3-year study, 1,300+ users with user-level ground truth, 88,000 measurements, 300+ features. With optimised feature sets, 89.2% of desktop users and about 72.7% to 72.9% of mobile users were trackable; optimising for stability gave mean stability periods of about 10.7 to 11.9 weeks. Sample skewed German, male, technical.
- What Clue can use: The best ground-truth estimate of *person-level* (not browser-level) trackability: high on desktop, much lower on mobile, with fingerprints stable for weeks not months.

### 4.8 Cao, Li, Wijmans, "(Cross-)Browser Fingerprinting via OS and Hardware Level Features" [PR]
- Citation: NDSS 2017.
- Link: https://www.ndss-symposium.org/wp-content/uploads/2017/09/ndss2017_02B-3_Cao_paper.pdf
- Summary: GPU, CPU and font-rendering tasks identify 99.24% of users (versus 90.84% for prior single-browser methods on the same data) and allow linking across different browsers on the same machine.
- What Clue can use: Cross-browser linking on one machine is possible in principle; it needs intrusive rendering tasks that most privacy regimes treat as fingerprinting requiring consent. Not a V0 technique.

### 4.9 Berke et al., "How Unique is Whose Web Browser? The role of demographics in browser fingerprinting among US users" [PR]
- Citation: A. Berke, E. Bacis, B. Ghazi, P. Kamath, R. Kumar, R. Lassonde, P. Manurangsi, U. Syed. PoPETs 2025(1). arXiv 2410.06954.
- Link: https://arxiv.org/abs/2410.06954
- Summary: 8,400 US participants with demographics. Fingerprint uniqueness varies by group: lower-income and older users are more identifiable; demographics can be inferred from standard browser attributes.
- What Clue can use: Fingerprint-based confidence is not uniform across visitors; calibration must be checked by segment.

### 4.10 Bacis, Bilogrevic, Busa-Fekete, Herath, Sartori, Syed, "Assessing Web Fingerprinting Risk" [PR]
- Citation: WWW 2024 (Companion). arXiv 2403.15607.
- Link: https://arxiv.org/abs/2403.15607
- Summary: Google researchers estimate fingerprinting entropy over tens of millions of real Chrome browsers while accounting for correlations among Web APIs and limiting information collected per user.
- What Clue can use: Method for measuring entropy of Clue's own feature set without collecting too much from any one visitor.

### 4.11 Iqbal, Englehardt, Shafiq, "Fingerprinting the Fingerprinters: Learning to Detect Browser Fingerprinting Behaviors" [PR]
- Citation: IEEE S&P 2021. arXiv 2008.04480.
- Link: https://arxiv.org/abs/2008.04480
- Summary: FP-Inspector finds fingerprinting on more than 10% of the top 100K sites and over a quarter of the top 10K.
- What Clue can use: Browser vendors and blockers detect fingerprinting scripts with ML; an aggressive fingerprinting snippet risks being blocked, which would also take down Clue's legitimate first-party signals.

### 4.12 Liu, Dani, Cao, Wu, Saxena, "The First Early Evidence of the Use of Browser Fingerprinting for Online Tracking" (FPTrace) [PR]
- Citation: WWW 2025. arXiv 2409.15656.
- Link: https://arxiv.org/abs/2409.15656
- Summary: Changes fingerprint attributes and observes ad bid values; bid disparities show fingerprinting is used for ad tracking and targeting, including after GDPR/CCPA opt-outs.
- What Clue can use: Confirms fingerprinting is part of the commercial identity stack. Also a compliance warning: fingerprinting that survives opt-out is what regulators look for.

### 4.13 Related persistence mechanisms (brief) [PR]
- Sy, Burkert, Federrath, Fischer, "Tracking Users across the Web via TLS Session Resumption", ACSAC 2018, arXiv 1810.07304: with common browser settings users trackable up to 8 days; with a 7-day lifetime 65% trackable permanently.
- Solomos, Kristoff, Kanich, Polakis, "Tales of Favicons and Caches: Persistent Tracking in Modern Browsers", NDSS 2021 (title confirmed).
- What Clue can use: Context only. These are supercookie techniques browsers patch; Clue should not use them.

---

## 5. Cross-site and cross-context identity leakage

### 5.1 Su, Shukla, Goel, Narayanan, "De-anonymizing Web Browsing Data with Social Networks" [PR]
- Citation: WWW 2017, pp. 1261-1269. DOI 10.1145/3038912.3052714.
- Link: https://5harad.com/papers/twivacy.pdf
- Summary: Each person's social feed is distinctive, so the links they click are a fingerprint. Maximum-likelihood matching against 300M+ Twitter profiles: with 30 Twitter-originated links in a history, the correct profile is found more than 50% of the time in simulation; on 374 real donated histories, 72% were identified. Several trackers see enough of the web to run the attack.
- What Clue can use: Behavioural content matching can identify a person against a public social graph. For B2B the analogue is matching the set of pages a visitor reads against public signals (e.g. a LinkedIn post they shared). Methodologically important; ethically and legally sensitive for Clue to operationalise.

### 5.2 Bird, Segall, Lopatka, "Replication: Why We Still Can't Browse in Peace: On the Uniqueness and Reidentifiability of Web Browsing Histories" [PR]
- Citation: SOUPS 2020.
- Link: https://www.usenix.org/system/files/soups2020-bird.pdf
- Summary: Two weeks of browsing from about 52,000 Firefox users: 48,919 distinct profiles, 99% unique, still unique when truncated to the top 100 sites. For users with 50+ distinct domains, about 50% re-identifiable using top-10K sites; over 80% for 150+ domains. Replicates Olejnik, Castelluccia, Janc (PETS 2012).
- What Clue can use: Browsing histories are near-unique, but Clue only sees one site's history per visitor, which is far too thin for this attack. It does support a first-party "returning-visitor re-linking" feature from page sequences.

### 5.3 Olejnik, Castelluccia, Janc, "Why Johnny Can't Browse in Peace: On the Uniqueness of Web Browsing History Patterns" [PR]
- Citation: PETS (HotPETs) 2012.
- Link: (title, authors and venue confirmed via Semantic Scholar; see 5.2 for the replication's numbers)
- What Clue can use: Original source for history uniqueness.

### 5.4 Krishnamurthy, Wills, "On the Leakage of Personally Identifiable Information via Online Social Networks" [PR]
- Citation: ACM WOSN (SIGCOMM workshop) 2009. DOI 10.1145/1592665.1592668.
- Link: https://dl.acm.org/doi/10.1145/1592665.1592668
- Summary: Social networks consistently leaked user identifiers to third parties via Request-URIs, Referer headers and cookies.
- What Clue can use: Referrers once carried identity; modern default Referrer-Policy (strict-origin-when-cross-origin) strips paths, so Clue should expect only origin-level referrers (e.g. "came from linkedin.com"), never a profile URL.

### 5.5 Staicu, Pradel, "Leaky Images: Targeted Privacy Attacks in the Web" [PR] DO NOT BUILD
- Citation: USENIX Security 2019.
- Link: https://www.usenix.org/system/files/sec19-staicu.pdf
- Summary: An image privately shared with one user loads only for that user's logged-in browser, so an attacker page can test "is this visitor person X". At least 8 of the 30 most popular image-sharing sites were affected, including Facebook and Twitter; works without JavaScript.

### 5.6 Sudhodanan, Khodayari, Caballero, "Cross-Origin State Inference (COSI) Attacks: Leaking Web Site States through XS-Leaks" [PR] DO NOT BUILD
- Citation: NDSS 2020. arXiv 1908.02204.
- Link: https://arxiv.org/abs/1908.02204
- Summary: Generalises login-detection attacks into 40 COSI attack classes, including de-anonymising the owner of an account.

### 5.7 Knittel, Mainka, Niemietz, Noss, Schwenk, "XSinator.com: From a Formal Model to the Automatic Evaluation of Cross-Site Leaks in Web Browsers" [PR] DO NOT BUILD
- Citation: ACM CCS 2021, pp. 1771-1788 (best paper).
- Link: https://xsinator.com/paper.pdf
- Summary: Formal model of XS-Leaks; 14 new attack classes; 34 leaks tested across 56 browser/OS combinations.

### 5.8 Zaheri, Oren, Curtmola, "Targeted Deanonymization via the Cache Side Channel: Attacks and Defenses" [PR] DO NOT BUILD
- Citation: USENIX Security 2022, pp. 1505-1523.
- Link: https://www.usenix.org/system/files/sec22-zaheri.pdf
- Summary: A malicious page tests whether a visitor holds a given public identifier (email, Twitter handle) on Google, Twitter, LinkedIn, TikTok, Facebook, Instagram, Reddit via the CPU cache side channel, bypassing CORP/COOP/SameSite; usually under 3 seconds; works in Tor Browser. Mobile follow-up: Blacha, Oren, Curtmola, "Leaky Apps: Targeted Deanonymization on Mobile Phones", CODASPY 2026, finds the mobile attack surface larger.
- What Clue can use (5.5 to 5.8 together): These prove that a site *can* test "is this visitor person X" when X is a known target, which is exactly the ABM framing. They are attacks on other sites' isolation, unlawful to deploy, and browser vendors patch them. Clue must never do this; the register lists them so the team can recognise vendor methods that smell like it.

### 5.9 Gelernter, Herzberg, "Cross-Site Search Attacks" [PR] DO NOT BUILD
- Citation: ACM CCS 2015. Title confirmed. Timing attacks on search features of other sites to extract private data.

### 5.10 Korolova (2010) and Faizullabhoy and Korolova (2018): microtargeting attacks on ad platforms [PR] DO NOT BUILD
- Citations: A. Korolova, "Privacy Violations Using Microtargeted Ads: A Case Study", IEEE ICDM Workshops 2010; I. Faizullabhoy, A. Korolova, "Facebook's Advertising Platform: New Attack Vectors and the Need for Interventions", arXiv 1803.10099, 2018.
- Links: https://doi.org/10.1109/ICDMW.2010.137 ; https://arxiv.org/abs/1803.10099
- Summary: Ad targeting narrow enough to reach one person leaks private attributes and can single out individuals; custom audiences extended the attack surface.
- What Clue can use: Platform-side "matched audience" routes (LinkedIn, Meta) are designed to resist single-person resolution; Clue's ad-activation features should stay at audience level.

---

## 6. Re-identification theory that underpins probabilistic person matching

### 6.1 Sweeney, "Simple Demographics Often Identify People Uniquely" [PR, working paper]
- Citation: L. Sweeney, Carnegie Mellon University Data Privacy Working Paper 3, 2000.
- Link: https://doi.org/10.1184/R1/6625769.V1
- Summary: 87% of the US population is unique on 5-digit ZIP, sex and full date of birth (as cited in Golle and Partridge 2009).

### 6.2 Golle, Partridge, "On the Anonymity of Home/Work Location Pairs" [PR]
- Citation: Pervasive 2009.
- Link: https://crypto.stanford.edu/~pgolle/papers/commute.pdf
- Summary: Knowing a person's home and work location, the median anonymity set in the US working population is 1, 21 and 34,980 at census block, tract and county granularity.
- What Clue can use: Directly relevant: Mishra et al. (3.1) show that a device's IP set reveals home and work networks. **(Home ISP block, office network) is a near-unique pair at fine granularity.** A cookie seen on both a company's office IP block and a residential IP is a strong person-level key for Clue's own first-party linking, without any third-party data.

### 6.3 de Montjoye, Hidalgo, Verleysen, Blondel, "Unique in the Crowd: The privacy bounds of human mobility" [PR]
- Citation: Scientific Reports 3:1376, 2013.
- Link: https://doi.org/10.1038/srep01376
- Summary: 1.5M people, 15 months: four spatio-temporal points uniquely identify 95%; uniqueness decays only as about the 1/10 power of resolution.
- What Clue can use: A handful of (network, hour) observations is enough to single out a device; coarsening does not buy much privacy, which matters for Clue's own retention design.

### 6.4 Rocher, Hendrickx, de Montjoye, "Estimating the success of re-identifications in incomplete datasets using generative models" [PR]
- Citation: Nature Communications 10:3069, 2019.
- Link: https://doi.org/10.1038/s41467-019-10933-3
- Summary: Copula model predicts individual uniqueness with AUC 0.84 to 0.97; 99.98% of Americans would be correctly re-identified in any dataset with 15 demographic attributes.
- What Clue can use: A principled way to estimate "probability this match is the unique right person" given the attributes Clue has (company, role, city, seniority), rather than a hand-tuned score. Useful for calibrating the person-level confidence at Clue's 90% precision bar.

---

## 7. B2B specifics: reverse IP, work from home, person-level accuracy

**Finding first: no peer-reviewed study measuring person-level B2B visitor de-anonymisation accuracy was located.** Company-level reverse-IP accuracy is also unmeasured in the academic literature; what exists is (a) network-measurement work on IP-to-organisation mapping (Prefix2Org, ASdb, already in WVI-2; Cai and Heidemann 3.4), (b) the B2C IP-linkage audit by Truthset (1.6), and (c) vendor patents and blogs.

### 7.1 6sense, "How 6sense Matches Remote Workers to the Right Accounts" (Q&A with CTO Viral Bajaria) [VEN]
- Link: https://6sense.com/blog/intent-identification-and-the-shift-to-working-from-home-qa-with-viral-bajaria-cto-of-6sense/
- Summary: Company Graph maps new IPs to accounts probabilistically when several people share a connection, and uses mobile advertising IDs as a secondary marker to triangulate across IPs. Claims "over 85%" accuracy (undefined metric, no ground truth stated). Notes that corporate VPNs usually tunnel only corporate resources, so general browsing exits on the home ISP.
- What Clue can use: The vendor confirms the mechanism: once a device has been seen on an office network, its later home IPs inherit the company. Clue can implement the first-party version (cookie seen on office IP, later seen on home IP).

### 7.2 6sense, "6sense Now Leverages IPv6 for Better Account Matching" [VEN]
- Link: https://6sense.com/blog/6sense-now-leverages-ipv6-for-better-account-matching/
- Summary: Announces predictive IPv6-to-account matching; gives no numbers.
- What Clue can use: Confirms IPv6 prefix-level matching is in production at a major vendor; Truthset (1.6) says commercial graphs still under-represent IPv6.

### 7.3 Bombora, "Company Surge intent data continues to deliver despite challenges like remote work" [VEN]
- Link: https://bombora.com/blog/bomboras-company-surge-intent-data-still-works-despite-challenges-like-remote-work-and-the-cookieless-future/
- Summary: Resolves remote workers via consented IPs and first-party cookies from its publisher co-op, a "graph-of-graphs" with partners such as LiveRamp, and behavioural modelling. No resolution rates given.
- What Clue can use: The co-op model (many publishers share first-party identity events) is how intent vendors get coverage; Clue has no co-op, so its coverage will be bounded by its customers' own traffic plus whatever it licenses.

### 7.4 Industry person-level match-rate claims [VEN]
- Trade comparisons located during this sweep (e.g. https://www.leadpipe.com/blog/rb2b-review/ , https://www.vector.co/compare/can-6sense-identify-anonymous-website-visitors) state vendor match rates (e.g. one vendor claims 35%+ person-level match of US B2B traffic) without disclosed ground truth (the 35% figure is as summarised in search results; the source pages were not opened). Not evidence; listed so the team knows these are claims.

---

## 8. Patents describing visitor-identification and identity-graph methods

No patents assigned to RB2B (Retention.com), Warmly, Vector or Leadpipe were found in the patent search conducted for this sweep. Patents located for the others:

### 8.1 6sense, US 10,536,427 B2, "De-anonymizing an anonymous IP address by aggregating events into mappings where each of the mappings associates an IP address shared by the events with an account" [PAT]
- Assignee 6Sense Insights. Inventors V. Bajaria, P. Shah, N. Vijayvargiya, D. Chang. Priority 22 Dec 2017.
- Link: https://patents.google.com/patent/US10536427B2/en ; sibling US 10,873,560 "Mapping anonymous entities to accounts for de-anonymization of online activities" https://patents.justia.com/patent/10873560 ; WO2019125858A1.
- Method: Events (IP, timestamp, event info) from websites, marketing-automation platforms (form fills, logins), cookie trackers and vendor data are normalised and aggregated into IP-to-account mappings (account derived from the email/second-level domain). Confidence combines: time confidence (sigmoid of span versus time since last activity), statistical confidence (log of spread across time periods and event count, weighted 0.5/0.5), and source confidence (each source scored against a "truth set" of mappings corroborated by at least 2 to 3 independent sources; combined as 1 minus the product of (1 minus source confidence)). Overall = 0.7 x (source + (1 minus source) x statistical) + 0.3 x time. An "ISP filter" drops an IP when the top account does not hold a large enough share of total confidence (threshold relaxes as confidence rises). Large alias sets, big web-service IP ranges, and geographically inconsistent events are cleaned out.
- What Clue can use: A complete, published recipe for company-level IP resolution from first-party form/login events. Clue can implement the same three-part confidence (recency, frequency/spread, multi-source corroboration) and the dominance filter on its own customers' form fills.

### 8.2 Demandbase, US 8,412,847 B2, "Mapping network addresses to organizations" [PAT]
- Assignee Demandbase. Inventor M. D. Longo. Priority 2 Nov 2009. Related publications US20110106920A1, US20130173791A1, US 9,419,850 B2.
- Link: https://patents.google.com/patent/US8412847B2/en
- Method: Evidence from (1) users typing a company name into web forms, captured with their IP; (2) bulk data of email opens (recipient domain plus opening IP); (3) emails with embedded remote content to capture the opener's IP. Candidate IP-organisation pairs are scored on geographic distance to known offices, number of distinct responses from the IP, business-hours and weekday timing, whether the IP has been associated with multiple organisations (shared/public use lowers the score), and consistency with registries such as ARIN. Pairs above a threshold are stored.
- What Clue can use: Business-hours and weekday weighting, multi-organisation penalties and registry consistency are cheap features Clue can compute from its own data. Note the method relies on email-open IPs, which Apple Mail Privacy Protection now masks for many recipients.

### 8.3 BitSight, US 10,554,619 B2, "Methods for mapping IP addresses and domains to organizations using user activity data" [PAT]
- Assignee BitSight Technologies. Inventors D. Dahlberg, S. Boyer, N. Venna, P. J. S. Gladstone. Priority 22 Jun 2017.
- Link: https://patents.google.com/patent/US10554619B2/en
- Method: Datasets from email service providers pairing mailbox domain with the IP used to access it. Filters: minimum number of distinct mailboxes from the organisation on the IP; the organisation's domain should be roughly 40% to 60% or more of activity on that IP; a high share of free-mail addresses marks public/guest/conference networks; temporal consistency; exclusion of residential, cellular and public Wi-Fi networks; associations expire on conflicting evidence or inactivity.
- What Clue can use: Concrete thresholds for deciding an IP is "an office of company X": several distinct people from that company, dominance of the company domain, low free-mail share. Directly usable on Clue customers' form-fill and login data.

### 8.4 Bombora, US 11,631,015 B2, "Machine learning techniques for internet protocol address to domain name resolution systems" [PAT]
- Assignee Bombora. Inventors include E. G. Matlick, R. J. Armstrong, B. Lin, N. E. Halecky, W. Kurt, N. Mann, J. Kruk. Filed 10 Sep 2020, granted 18 Apr 2023.
- Link: https://patents.google.com/patent/US11631015B2/en
- Method: Supervised model over (IP, domain, source) tuples from multiple third-party IP-to-domain providers; features are IP-level, domain-level and "source vote" features; predicts the most likely domain for an IP, resolving cases where sources map many domains to one IP. No accuracy numbers or WFH handling disclosed.
- What Clue can use: If Clue licenses more than one IP-to-company feed, it should treat them as voters in a learned ensemble, not pick one.

### 8.5 Drawbridge (now Microsoft), US 9,514,248 B1, "System to group internet devices based upon device usage" [PAT]
- Assignee Microsoft Technology Licensing (from Drawbridge). Inventors D. Guan, X. Li, R. Cotta, R. Bafna, O. Venkatesan. Priority 7 Oct 2015.
- Link: https://patents.google.com/patent/US9514248B1/en
- Method: From (device ID, IP, timestamp) triads, candidate pairs are devices sharing an IP (typically residential IPs with fewer than about six devices), scored with Bayesian support/confidence; rule-based feature vectors (shared content categories, geography, time-of-day patterns); semi-supervised scoring (unsupervised pre-training, then Bayesian networks or tree ensembles trained on labelled same-user pairs, ~20% held out); graph clustering by label propagation or simulated annealing. No accuracy numbers in the patent (Nielsen-reported figure in 1.7).
- What Clue can use: The canonical probabilistic device-graph pipeline: candidate generation by small-population IPs, pair features, calibrated pair scores, then clustering. Clue's first-party cookie-clustering can follow this shape at small scale.

### 8.6 Tapad, US 2013/0124309 A1, "Managing associations between device identifiers" [PAT]
- Assignee Tapad. Inventors A. H. Traasdahl, D. O. Liodden, V. W.-H. Chang. Priority 15 Nov 2011. A related USPTO patent, "Network-based probabilistic device linking" (11,184,449), surfaced in the same search and scores device-to-IP connections by frequency of use within a time window; its assignee was not verified in this sweep.
- Link: https://patents.google.com/patent/US20130124309A1/en
- Method: Links device IDs when they appear on the same network (e.g. home Wi-Fi) or use the same login at a partner. Edge weights rise with recent co-occurrence and decay when co-occurrence stops (e.g. 30 days). Discards networks with more than a threshold of devices in a short window (example: five devices in one hour) as proxies or public networks.
- What Clue can use: The "high-population network" filter is the simplest defence against office and CGN IPs polluting person links: an IP with many distinct devices per hour is a company or carrier, useful for company inference, useless for person inference.

### 8.7 US 2025/0055838 A1, "Federated identity resolution framework" (surfaced with LiveIntent material) [PAT]
- Link: https://patents.google.com/patent/US20250055838A1/en
- Note: the search that surfaced this publication associated it with LiveIntent's LiveConnect documentation; the assignee was not independently verified in this sweep.
- Method (from the patent and LiveIntent docs surfaced with it): Publishers' email newsletters carry an ESP user ID; when the user clicks through, the on-site tag captures it with first-party cookie, IP, user agent and any on-page hashed email, building HEM-to-cookie links; resolves across multiple ID schemes under each scheme's usage rules.
- What Clue can use: Validates the "own-email click to first-party cookie" route as the core deterministic method in the industry. Clue can do the same with its customers' own sends, entirely first-party.

### 8.8 Viant (Vindico), US 8,996,727 B2, "Internet connected household identification for online measurement and dynamic content delivery" [PAT]
- Assignee Viant Technology. Inventors B. C. DeFrancesco, T. C. Vanderhook, C. J. Vanderhook. Priority 17 May 2012. Same-titled US patents 9,331,921, 10,764,240, 11,310,195, 11,463,403, 11,936,618, 12,308,990 and "Out-of-home internet connected household identification" 11,936,703 appear to be the same family (assignee not individually verified).
- Link: https://patents.google.com/patent/US8996727B2/en
- Method: An IP counts as a household only if (1) it belongs to an ISP offering residential service (from RIR data), (2) device activity stays below a threshold (businesses are busier), and (3) its assignment age exceeds a threshold (example 45 days), with cookie/device continuity used to chain rotating IPs.
- What Clue can use: A simple, explainable household-IP qualifier Clue can apply before trusting any IP as a person-level clue.

### 8.9 LiveRamp, US 2020/0244537 A1, "Computing Environment Node and Edge Network to Optimize Data Identity Resolution" [PAT]
- Link: https://patents.google.com/patent/US20200244537A1/en
- Method: Identity resolution over a node-and-edge graph, using entity-resolution scores (e.g. from Acxiom's AbiliTec) as edge conductivity inputs.
- What Clue can use: Confirms that the largest deterministic graph treats links as weighted edges, not facts; Clue's claim-with-provenance model already matches this.

### 8.10 Tealium, US 8,805,946 B1, "System and method for combining content site visitor profiles" [PAT]
- Inventor C. Glommen. Priority 30 Aug 2013. Later visitor-profile combining/separating publications (US12132796B2, WO2023194923A1, priority 2022) surfaced in the same search; their assignee was not verified.
- Link: https://patents.google.com/patent/US8805946B1/en
- Method: Merge visitor profiles when a persistent identifier (email, login, phone, social ID, address) matches across sessions or devices.
- What Clue can use: The deterministic "stitch on login" pattern every CDP uses; Clue's first-party cookie should merge on any declared identifier.

### 8.11 The 41st Parameter (Experian), US 7,853,533, "Time Differential Linking" device identification [PAT]
- Link: https://patents.justia.com/assignee/the-41st-parameter-inc ; press https://www.darkreading.com/cyber-risk/41st-parameter-awarded-patent-for-device-identification-for-online-and-mobile-commerce ; see also US 9,900,312 B2, "Using clock drift, clock skew, and network latency to enhance machine identification" (assignee not verified in this sweep).
- Method: Adds the difference between the device's clock/time zone and server time to device-fingerprint attributes for fraud-grade device recognition; the vendor claimed large accuracy gains (unverified marketing figures).
- What Clue can use: Clock offset and time zone are cheap, low-entropy features that help separate devices behind one office IP.

### 8.12 Rye and Beverly, US 12,021,829 B2, "Discovering and clustering IPv6 addresses by hardware identifiers" [PAT]
- Link: https://patents.google.com/patent/US12021829B2/en
- Patent counterpart to IPvSeeYou (3.9). Not for Clue use.

---

## 9. Synthesis: what the literature implies for Clue

1. **Third-party IP-to-person graphs are mostly wrong.** Truthset's ISP-ground-truth audit (1.6) is the anchor: 13% to 16% average accuracy, providers rarely agree. Email-to-household links are about 51% (1.5). Any vendor promising 90%+ person-level precision from IP alone is contradicted by the only independent ground truth located.
2. **Company-level IP resolution is a solved, patented recipe on first-party data.** The 6sense, Demandbase and BitSight patents (8.1 to 8.3) all build IP-to-company maps from form fills, logins and email activity with recency, frequency, multi-source corroboration, dominance and free-mail filters. Clue can do this on its customers' own forms with no third-party data.
3. **Person-level identity on first-party data comes from deterministic events plus linking.** Email clicks with a first-party token (2.1, 8.7), form submits and logins (2.6, 8.10), then propagation by first-party cookie, evolution-aware fingerprint linking (4.5, 4.7) and the (office network, home network) pair (3.1, 6.2).
4. **IP is a weeks-long household pseudonym on fixed broadband, useless on mobile and relays.** 87% of users keep an IP for over a month (3.1), but CGN covers more than 90% of cellular ASes (3.5), IPv6 addresses are short-lived below the prefix (3.7), and Private Relay rotates egress (3.10).
5. **Fingerprints are weak alone in the general population** (33.6% unique, 18.5% mobile; 4.3) and decay in days (4.5), but are useful as a tie-breaker inside an IP or office block.
6. **The strongest de-anonymisation results in the literature are attacks or require platform-scale data** (1.1, 5.1, 5.5 to 5.8). Clue should treat these as the boundary of the possible, not a toolkit.

## 10. Gaps the literature does not fill

- No independent, ground-truthed measurement of B2B company-level reverse-IP precision/recall, before or after the work-from-home shift.
- No independent measurement of person-level B2B visitor identification (RB2B-style) precision.
- No measurement study located on how Apple Mail Privacy Protection affected email-open-to-IP mapping (relevant to Demandbase-style evidence).
- No study located on LinkedIn Insight Tag data flows comparable to the Meta Pixel studies (2.8, 2.9).
- DynamIPs (3.3) numbers on IPv6 prefix stability were not extracted in this sweep and should be read before IPv6 keys are designed.

These gaps argue for Clue running its own ground-truth evaluation (customers' known form-fill and login identities held out as labels) rather than relying on published or vendor numbers.

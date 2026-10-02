# Gemini transcript — Boardroom Club: AI Summit: Sanaz Yashar (Zafran Security)
source_mp3: https://anchor.fm/s/f695d6d8/podcast/play/106390290/https%3A%2F%2Fd3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2025-7-9%2F405396769-44100-2-7287bb9271f44.mp3
model: gemini-3.5-flash-lite
duration: 00:42:49

## META
speakers:
  S1 (Yossi Carmazin): host of the boardroom club podcast, introduces guests and asks questions
  S2 (Sanaz Yashar): co-founder and CEO of Zafran Security, guest
guest_identity_evidence: "No other than Sanaz Yashar, co-founder and CEO of Zafran Security"
duration_mmss: 43:53

## TRANSCRIPT
[00:00] S1 (Yossi Carmazin): Hi everybody, good afternoon, good evening and good morning wherever you are.
[00:03] S1 (Yossi Carmazin): Thank you very much for joining the Boardroom Club today to our AI summit, featuring an executive from top tech companies revolutionizing the world as we speak.
[00:11] S1 (Yossi Carmazin): My name is Yossi Carmazin and I'm joined also by a good friend of mine, Alvaro Jimenez.
[00:15] S1 (Yossi Carmazin): Alvaro, good to be here, yes.
[00:18] S1 (Yossi Carmazin): So today we are fortunate enough to interview none other than Sanaz Yashar, co-founder and CEO of Zafran Security, the threat exposure management platform.
[00:26] S1 (Yossi Carmazin): Zafran helps companies quickly identify and reduce real threats without relying solely on patching.
[00:32] S1 (Yossi Carmazin): Among their investors, you could find Sequoia, Cyberstarts and even Pennyjar of the great Steph Curry.
[00:38] S1 (Yossi Carmazin): So Senaz, thank you so much for joining us today.
[00:41] S2 (Sanaz Yashar): Thank you so much, having me.
[00:43] S1 (Yossi Carmazin): Yeah, so Senaz, you have a fascinating story, so I thought to start by asking you if you can share with us a little bit about your early life and what led you to the tech world and specifically to the cybersecurity space?
[00:55] S2 (Sanaz Yashar): Okay, yes, of course.
[00:57] S2 (Sanaz Yashar): I was always the different one.
[01:01] S2 (Sanaz Yashar): I was born and raised in Iran, Tehran, moved uh.
[01:04] S1 (Yossi Carmazin): So Izra was very good in chemistry and biology in the chemistry class and even the Olympiads.
[01:10] S2 (Sanaz Yashar): Moving forward a couple of years to Israel, I was the youngest in the class in the university because it was like pre-IDF.
[01:19] S2 (Sanaz Yashar): And then I went to the IDF, so I was like this different as well.
[01:23] S2 (Sanaz Yashar): I was like the biologist doing cyber.
[01:25] S2 (Sanaz Yashar): And then coming out of the IDF to the commercial world, I think I have like all the different colors and frequencies that I could gathered to during my career path to make me ready for this job.
[01:39] S2 (Sanaz Yashar): But coming from Iran to Israel, coming from biology and chemistry to the world of cybersecurity, it has been a great perspective and I owe a lot of my career to that, I think.
[01:52] S1 (Yossi Carmazin): So, yeah, so I can tell you definitely not the most conventional path to say the least.
[01:56] S1 (Yossi Carmazin): And I actually also learned biology and chemistry, but only back in high school.
[02:01] S2 (Sanaz Yashar): So, oh, interesting.
[02:04] S2 (Sanaz Yashar): We should do some gathering.
[02:06] S1 (Yossi Carmazin): Yeah, so it's actually a great segue to my next question because you started biology, but what lessons did you learn there that helped shape your approach to cybersecurity?
[02:18] S2 (Sanaz Yashar): And do you see any similarities between these two worlds?
[02:18] S2 (Sanaz Yashar): For sure, yes.
[02:19] S2 (Sanaz Yashar): First of all, I can tell you that when I started my cyber career, even the name was not cyber.
[02:27] S2 (Sanaz Yashar): It was also not security.
[02:29] S2 (Sanaz Yashar): Uh, I did all my career in cyber in an offensive cyber, what we called under the government, of course, and doing counter-terror.
[02:37] S2 (Sanaz Yashar): But I think it took at least 10 years when the cyber word even used before that, right?
[02:44] S2 (Sanaz Yashar): Before that it was like hacking or interception and these kind of stuff.
[02:48] S2 (Sanaz Yashar): And still when there is a lot in common between I was in microbiology, which which means that you have to understand how actually your or the organism is is mixed of a code.
[03:02] S2 (Sanaz Yashar): The code is according to DNA, the DNA is coding to RNA, the RNA is coding to protein, right?
[03:09] S2 (Sanaz Yashar): And this is how we can describe the life organism.
[03:14] S2 (Sanaz Yashar): And this is what it is also about cyber.
[03:16] S2 (Sanaz Yashar): At the end, there is a lot about the code behind the scene, which different functionality this code can bring on with them.
[03:26] S2 (Sanaz Yashar): Which kind of bugs or an efficiency this code have that you can hack in.
[03:31] S2 (Sanaz Yashar): And at the same time, how this code moving mutations, like from one creature to become another creature.
[03:40] S2 (Sanaz Yashar): There is a lot of different mutations, and the question is like how you can catalyze or block these kind of changes that the code is actually going through.
[03:51] S2 (Sanaz Yashar): I believe as live organism for the biology, there are two main things that I get from it to the cyber.
[03:59] S2 (Sanaz Yashar): First of all, understanding the behind the scene and the code is matters, but also understanding the phenotype and how this code being evaluated and bringing value to the customers, it matters a lot.
[04:13] S2 (Sanaz Yashar): The same like biology looks like when there is a certain functionality in the code and there is a certain bug in the code, you have compensated controls in your body, too, in order to fix it.
[04:27] S2 (Sanaz Yashar): Unfortunately, this is when the stuff starts to distinguish.
[04:32] S2 (Sanaz Yashar): When it comes to software and tools, it doesn't look that it's almost a self-healing platform.
[04:40] S2 (Sanaz Yashar): Like everything, for everything, you need an operator to fix, right?
[04:44] S2 (Sanaz Yashar): Like when you find these inefficiencies in the code, what we call vulnerabilities, at the end, it's not automatically healing.
[04:54] S2 (Sanaz Yashar): And you ask yourself, how our body is so much efficient compared to amazing software and tools when they always need an operator?
[05:06] S2 (Sanaz Yashar): And the biggest pain of cybersecurity when you come from the offensive war to the defensive war, the biggest pain is we don't have enough operators to operate all the different vulnerabilities.
[05:20] S2 (Sanaz Yashar): Like there is so much code and so much vulnerabilities, and with an AI, you write even more code and more vulnerabilities and more attacks surface, but you don't have enough operators in the world that they can actually fix stuff.
[05:34] S2 (Sanaz Yashar): And I believe the next generation of cybersecurity, it should look more like biology, when it's a self-healing platform, right?
[05:44] S2 (Sanaz Yashar): That that you learn where are the biggest bugs and the vulnerabilities and the cracks and you know how to automatically remediate and mitigate those with some compensated controls.
[05:56] S1 (Yossi Carmazin): Yeah, that's fascinating and I look forward to see how AI going to reshape cybersecurity and biology, and it's actually taking me to the next question because you started biology, but what lessons did you learn there that elk shaped your approach to cybersecurity?
[06:09] S1 (Yossi Carmazin): And do you see any similarities between these two worlds?
[06:11] S2 (Sanaz Yashar): You actually started Zafran as a result of a cybersecurity incident in an hospital that you worked in.
[06:16] S1 (Yossi Carmazin): So, can you share with us how the idea of Zafran security started and what actually happened there?
[06:22] S2 (Sanaz Yashar): I was a part of maybe the best cybersecurity services in the world, I'm not kidding.
[06:26] S2 (Sanaz Yashar): The name is Mandiant.
[06:27] S2 (Sanaz Yashar): They are the ones that they responded to the solar winds and to the hacks in the elections and Olympic games and a lot of like big, big, big stuff out there.
[06:38] S2 (Sanaz Yashar): I was heading a group for an investigation of an incident in the chain of hospitals, one of them unfortunately completely caught non-ready.
[06:50] S2 (Sanaz Yashar): That means the attacker, before they deployed the ransomware, they wiped also the backup, because the backup was connected to the network, which is the no no no, you don't do this kind of stuff.
[07:02] S2 (Sanaz Yashar): The attacker exploited a zero day three months prior to deploying the ransomware, that means at least three months, this a specific hospital could find out about something happening and try to remediate it faster.
[07:20] S2 (Sanaz Yashar): And during these three months, there were many security tools that I used them in order to do the investigation.
[07:27] S2 (Sanaz Yashar): They were already useless because I got all the alerts and forensic data that they could stop the ransomware, but unfortunately when we got to the place ransomware was already deployed, nothing was operational.
[07:39] S2 (Sanaz Yashar): They didn't have any data about the patients.
[07:43] S2 (Sanaz Yashar): And I remind you that it was like late Covid times, so we had patients that they were connected to machines and they had to move people from one hospital to another hospital, with put at risk lives of people.
[07:56] S2 (Sanaz Yashar): Um, which is very sad.
[07:59] S2 (Sanaz Yashar): So I was not working in the hospital, I was part of a group that is responding heading the response team for this hospital.
[08:08] S2 (Sanaz Yashar): After we finished the investigation, the best thing can happen to that incident response person or threat intel person, we call it attribution.
[08:17] S2 (Sanaz Yashar): Attribution is that when you know who was the threat actor, and exactly the kill chain, like what they did in order to hack that system.
[08:27] S2 (Sanaz Yashar): So it was so clear.
[08:29] S2 (Sanaz Yashar): It means the investigation was completely right, right?
[08:33] S2 (Sanaz Yashar): But this is how you call it, the surgery was successful, the patient died, but at the end, it was too late because we couldn't recover the files, right?
[08:41] S2 (Sanaz Yashar): And they couldn't also pay ransomware because it's a government hospital.
[08:47] S2 (Sanaz Yashar): They can, they are not allowed to pay the ransomware.
[08:51] S2 (Sanaz Yashar): So, when I saw that we had all the different data, nodes, uh, from network to endpoint, from the vulnerability that was exploited, the whole path and modus operandi of the threat actor inside the system, I knew that there is probably some other way to respond to vulnerabilities.
[09:19] S2 (Sanaz Yashar): That it's not the way we are doing it today.
[09:21] S2 (Sanaz Yashar): Today, it's like kind of simple, you do scan, right?
[09:24] S2 (Sanaz Yashar): And then you say, okay, have like, I'm not kidding, like when I say 30 million vulnerabilities, these are the real numbers we are seeing.
[09:33] S2 (Sanaz Yashar): 30 million vulnerabilities.
[09:35] S2 (Sanaz Yashar): So I have to go update, update, update, patch, patch, patch.
[09:39] S2 (Sanaz Yashar): And imagine like a hospital or any other company have to patch all the time.
[09:45] S2 (Sanaz Yashar): Like, how much annoying it is when even your laptop is doing the patch cycle.
[09:49] S2 (Sanaz Yashar): So they cannot work if they patch all the time.
[09:52] S2 (Sanaz Yashar): They also don't know which vulnerabilities the one is going to be exploited next.
[09:57] S2 (Sanaz Yashar): So they don't know how to eat this elephant, how to fix.
[10:01] S2 (Sanaz Yashar): And when you make from data insight, those insights is completely connected to the muscles of the organization and can move actions, then you will have a chance to be beyond the exploitation care.
[10:17] S2 (Sanaz Yashar): So, as I told you, around 10 percentage of all these millions of millions of vulnerabilities are exploitble.
[10:23] S2 (Sanaz Yashar): How we know that?
[10:24] S2 (Sanaz Yashar): We started with a certain asset.
[10:25] S2 (Sanaz Yashar): Asset could be your laptop, asset could be a server, asset could be a cloud asset.
[10:31] S2 (Sanaz Yashar): And then we add context of threat.
[10:34] S2 (Sanaz Yashar): Threat is red when defense is in blue.
[10:37] S2 (Sanaz Yashar): Have you heard about this?
[10:39] S2 (Sanaz Yashar): You know, the red space and the blue space, okay?
[10:42] S2 (Sanaz Yashar): So, uh, 101 security or cyber security, every time you think of a threat, you think red, and if you every time you think of the defense, you think blue.
[10:53] S2 (Sanaz Yashar): And this is how you have red teams, blue teams, and sometimes you have purple teams, which you understand that they are put together.
[11:01] S2 (Sanaz Yashar): So, we started with the threat risk.
[11:03] S2 (Sanaz Yashar): We understand the asset, and then we understand the context of the asset.
[11:07] S2 (Sanaz Yashar): How does it look?
[11:08] S2 (Sanaz Yashar): We check all the vulnerabilities that are mapped to this asset.
[11:13] S2 (Sanaz Yashar): We bring them ourselves, we integrate with other tools.
[11:17] S2 (Sanaz Yashar): Then we check the enemy of organizations, the enemy, but also the business is an internet, right?
[11:24] S2 (Sanaz Yashar): We check which of these assets are actually exposed to the internet or not.
[11:28] S2 (Sanaz Yashar): We have our own algo.
[11:29] S2 (Sanaz Yashar): And then we have a line of my favorite, which is like threat intel.
[11:33] S2 (Sanaz Yashar): What if there is a vulnerability, it's running, it's internet exposed, but there is no threat actor.
[11:38] S2 (Sanaz Yashar): Like you have an open window, you have a crown jewels of your table, but there is no thief in the city.
[11:44] S2 (Sanaz Yashar): Should you go and fix the window?
[11:46] S2 (Sanaz Yashar): Close the window if there is no thief.
[11:47] S2 (Sanaz Yashar): So, which check if there is a threat actor.
[11:51] S2 (Sanaz Yashar): So that we can prioritize.
[11:53] S2 (Sanaz Yashar): I think that we have 30 million vulnerabilities, but what we can actually fix is 10 percentage or 8 percentage, if you are 10 percentage, you are not in a good position.
[12:03] S2 (Sanaz Yashar): Like 7, 8 percentage of the vulnerabilities of being exploited.
[12:07] S2 (Sanaz Yashar): This is the applicable risk.
[12:09] S2 (Sanaz Yashar): So, from threat analysis, we move to the risk analysis and we bubble it up by understanding the threat, but also the layers of the security.
[12:17] S2 (Sanaz Yashar): And I tell you a secret, if somebody wants to build Zafran, first of all, don't do it.
[12:19] S2 (Sanaz Yashar): Talk to me first.
[12:21] S2 (Sanaz Yashar): But if somebody wants to build Zafran, this is the right order.
[12:26] S1 (Yossi Carmazin): Yeah, that's fascinating and I look forward to see how AI going to reshape cybersecurity and biology and it's actually taking me to the next question because you started biology, but what lessons did you learn there that elk shaped your approach to cybersecurity?
[12:38] S2 (AI): And do you see any similarities between these two worlds?
[12:41] S2 (Sanaz Yashar): For sure, yes.
[12:43] S2 (Sanaz Yashar): First of all, I can tell you that when I started my cyber career, even the name was not cyber.
[12:49] S2 (Sanaz Yashar): It was also not security.
[12:51] S2 (Sanaz Yashar): Uh, I did all my career in cyber in an offensive cyber, what we called under the government, of course, and doing counter-terror.
[12:59] S2 (Sanaz Yashar): But I think it took at least 10 years when the cyber word even used before that, right?
[13:06] S2 (Sanaz Yashar): Before that it was like hacking or interception and these kind of stuff.
[13:12] S2 (Sanaz Yashar): And still when there is a lot in common between I was in microbiology, which which means that you have to understand how actually your or the organism is is mixed of a code.
[13:30] S2 (Sanaz Yashar): The code is according to DNA, the DNA is coding to RNA, the RNA is coding to protein, right?
[13:39] S2 (Sanaz Yashar): And this is how we can describe the life organism.
[13:43] S2 (Sanaz Yashar): And this is what it is also about cyber.
[13:46] S2 (Sanaz Yashar): At the end, there is a lot about the code behind the scene, which different functionality this code can bring on with them.
[13:57] S2 (Sanaz Yashar): Which kind of bugs or an efficiency this code have that you can hack in.
[14:03] S2 (Sanaz Yashar): And at the same time, how this code moving mutations, like from one creature to become another creature.
[14:12] S2 (Sanaz Yashar): There is a lot of different mutations, and the question is like how you can catalyze or block these kind of changes that the code is actually going through.
[14:24] S2 (Sanaz Yashar): I believe as live organism for the biology, there are two main things that I get from it to the cyber.
[14:33] S2 (Sanaz Yashar): First of all, understanding the behind the scene and the code is matters, but also understanding the phenotype and how this code being evaluated and bringing value to the customers, it matters a lot.
[14:52] S2 (Sanaz Yashar): The same like biology looks like when there is a certain functionality in the code and there is a certain bug in the code, you have compensated controls in your body, too, in order to fix it.
[15:07] S2 (Sanaz Yashar): Unfortunately, this is when the stuff starts to distinguish.
[15:15] S2 (Sanaz Yashar): When it comes to software and tools, it doesn't look that it's almost a self-healing platform.
[15:23] S2 (Sanaz Yashar): Like everything, for everything, you need an operator to fix, right?
[15:30] S2 (Sanaz Yashar): Like when you find these inefficiencies in the code, what we call vulnerabilities, at the end, it's not automatically healing.
[15:43] S2 (Sanaz Yashar): And you ask yourself, how our body is so much efficient compared to amazing software and tools when they always need an operator?
[15:56] S2 (Sanaz Yashar): And the biggest pain of cybersecurity when you come from the offensive war to the defensive war, the biggest pain is we don't have enough operators to operate all the different vulnerabilities.
[16:13] S2 (Sanaz Yashar): Like there is so much code and so much vulnerabilities, and with an AI, you write even more code and more vulnerabilities and more attacks surface, but you don't have enough operators in the world that they can actually fix stuff.
[16:34] S2 (Sanaz Yashar): But coming from Iran to Israel, coming from biology and chemistry to the world of cybersecurity, it has been a great perspective and I owe a lot of my career to that, I think.
[16:51] S1 (Yossi Carmazin): So, yeah, so I can tell you definitely not the most conventional path to say the least.
[16:56] S1 (Yossi Carmazin): And I actually also learned biology and chemistry, but only back in high school.
[17:01] S2 (Sanaz Yashar): So, oh, interesting.
[17:04] S2 (Sanaz Yashar): We should do some gathering.
[17:06] S1 (Yossi Carmazin): Yeah, so it's actually a great segue to my next question because you started biology, but what lessons did you learn there that helped shape your approach to cybersecurity?
[17:16] S1 (Yossi Carmazin): And do you see any similarities between these two worlds?
[17:19] S2 (Sanaz Yashar): For sure, yes.
[17:20] S2 (Sanaz Yashar): First of all, I can tell you that when I started my cyber career, even the name was not cyber.
[17:28] S2 (Sanaz Yashar): It was also not security.
[17:30] S2 (Sanaz Yashar): Uh, I did all my career in cyber in an offensive cyber, what we called under the government, of course, and doing counter-terror.
[17:38] S2 (Sanaz Yashar): But I think it took at least 10 years when the cyber word even used before that, right?
[17:46] S2 (Sanaz Yashar): Before that it was like hacking or interception and these kind of stuff.
[17:53] S2 (Sanaz Yashar): And still when there is a lot in common between I was in microbiology, which which means that you have to understand how actually your or the organism is is mixed of a code.
[18:10] S2 (Sanaz Yashar): The code is according to DNA, the DNA is coding to RNA, the RNA is coding to protein, right?
[18:20] S2 (Sanaz Yashar): And this is how we can describe the life organism.
[18:24] S2 (Sanaz Yashar): And this is what it is also about cyber.
[18:28] S2 (Sanaz Yashar): At the end, there is a lot about the code behind the scene, which different functionality this code can bring on with them.
[18:37] S2 (Sanaz Yashar): Which kind of bugs or an efficiency this code have that you can hack in.
[18:43] S2 (Sanaz Yashar): And at the same time, how this code moving mutations, like from one creature to become another creature.
[18:53] S2 (Sanaz Yashar): There is a lot of different mutations, and the question is like how you can catalyze or block these kind of changes that the code is actually going through.
[19:04] S2 (Sanaz Yashar): I believe as live organism for the biology, there are two main things that I get from it to the cyber.
[19:13] S2 (Sanaz Yashar): First of all, understanding the behind the scene and the code is matters, but also understanding the phenotype and how this code being evaluated and bringing value to the customers, it matters a lot.
[19:32] S2 (Sanaz Yashar): The same like biology looks like when there is a certain functionality in the code and there is a certain bug in the code, you have compensated controls in your body, too, in order to fix it.
[19:47] S2 (Sanaz Yashar): Unfortunately, this is when the stuff starts to distinguish.
[19:55] S2 (Sanaz Yashar): When it comes to software and tools, it doesn't look that it's almost a self-healing platform.
[20:03] S2 (Sanaz Yashar): Like everything, for everything, you need an operator to fix, right?
[20:10] S2 (Sanaz Yashar): Like when you find these inefficiencies in the code, what we call vulnerabilities, at the end, it's not automatically healing.
[20:23] S2 (Sanaz Yashar): And you ask yourself, how our body is so much efficient compared to amazing software and tools when they always need an operator?
[20:37] S2 (Sanaz Yashar): And the biggest pain of cybersecurity when you come from the offensive war to the defensive war, the biggest pain is we don't have enough operators to operate all the different vulnerabilities.
[20:53] S2 (Sanaz Yashar): Like there is so much code and so much vulnerabilities, and with an AI, you write even more code and more vulnerabilities and more attacks surface, but you don't have enough operators in the world that they can actually fix stuff.
[21:13] S2 (Sanaz Yashar): But coming from Iran to Israel, coming from biology and chemistry to the world of cybersecurity, it has been a great perspective and I owe a lot of my career to that, I think.
[21:31] S1 (Yossi Carmazin): So, yeah, so I can tell you definitely not the most conventional path to say the least.
[21:36] S1 (Yossi Carmazin): And I actually also learned biology and chemistry, but only back in high school.
[21:41] S2 (Sanaz Yashar): So, oh, interesting.
[21:44] S2 (Sanaz Yashar): We should do some gathering.
[21:46] S1 (Yossi Carmazin): Yeah, so it's actually a great segue to my next question because you started biology, but what lessons did you learn there that helped shape your approach to cybersecurity?
[21:56] S1 (Yossi Carmazin): And do you see any similarities between these two worlds?
[21:59] S2 (Sanaz Yashar): For sure, yes.
[22:00] S2 (Sanaz Yashar): First of all, I can tell you that when I started my cyber career, even the name was not cyber.
[22:08] S2 (Sanaz Yashar): It was also not security.
[22:10] S2 (Sanaz Yashar): Uh, I did all my career in cyber in an offensive cyber, what we called under the government, of course, and doing counter-terror.
[22:18] S2 (Sanaz Yashar): But I think it took at least 10 years when the cyber word even used before that, right?
[22:26] S2 (Sanaz Yashar): Before that it was like hacking or interception and these kind of stuff.
[22:33] S2 (Sanaz Yashar): And still when there is a lot in common between I was in microbiology, which which means that you have to understand how actually your or the organism is is mixed of a code.
[22:50] S2 (Sanaz Yashar): The code is according to DNA, the DNA is coding to RNA, the RNA is coding to protein, right?
[22:59] S2 (Sanaz Yashar): And this is how we can describe the life organism.
[23:03] S2 (Sanaz Yashar): And this is what it is also about cyber.
[23:07] S2 (Sanaz Yashar): At the end, there is a lot about the code behind the scene, which different functionality this code can bring on with them.
[23:17] S2 (Sanaz Yashar): Which kind of bugs or an efficiency this code have that you can hack in.
[23:23] S2 (Sanaz Yashar): And at the same time, how this code moving mutations, like from one creature to become another creature.
[23:33] S2 (Sanaz Yashar): There is a lot of different mutations, and the question is like how you can catalyze or block these kind of changes that the code is actually going through.
[23:44] S2 (Sanaz Yashar): I believe as live organism for the biology, there are two main things that I get from it to the cyber.
[23:53] S2 (Sanaz Yashar): First of all, understanding the behind the scene and the code is matters, but also understanding the phenotype and how this code being evaluated and bringing value to the customers, it matters a lot.
[24:12] S2 (Sanaz Yashar): The same like biology looks like when there is a certain functionality in the code and there is a certain bug in the code, you have compensated controls in your body, too, in order to fix it.
[24:27] S2 (Sanaz Yashar): Unfortunately, this is when the stuff starts to distinguish.
[24:35] S2 (Sanaz Yashar): When it comes to software and tools, it doesn't look that it's almost a self-healing platform.
[24:43] S2 (Sanaz Yashar): Like everything, for everything, you need an operator to fix, right?
[24:50] S2 (Sanaz Yashar): Like when you find these inefficiencies in the code, what we call vulnerabilities, at the end, it's not automatically healing.
[25:03] S2 (Sanaz Yashar): And you ask yourself, how our body is so much efficient compared to amazing software and tools when they always need an operator?
[25:17] S2 (Sanaz Yashar): And the biggest pain of cybersecurity when you come from the offensive war to the defensive war, the biggest pain is we don't have enough operators to operate all the different vulnerabilities.
[25:33] S2 (Sanaz Yashar): Like there is so much code and so much vulnerabilities, and with an AI, you write even more code and more vulnerabilities and more attacks surface, but you don't have enough operators in the world that they can actually fix stuff.
[25:53] S2 (Sanaz Yashar): But coming from Iran to Israel, coming from biology and chemistry to the world of cybersecurity, it has been a great perspective and I owe a lot of my career to that, I think.
[26:11] S1 (Yossi Carmazin): So, yeah, so I can tell you definitely not the most conventional path to say the least.
[26:16] S1 (Yossi Carmazin): And I actually also learned biology and chemistry, but only back in high school.
[26:21] S2 (Sanaz Yashar): So, oh, interesting.
[26:24] S2 (Sanaz Yashar): We should do some gathering.
[26:26] S1 (Yossi Carmazin): Yeah, so it's actually a great segue to my next question because you started biology, but what lessons did you learn there that helped shape your approach to cybersecurity?
[26:36] S1 (Yossi Carmazin): And do you see any similarities between these two worlds?
[26:39] S2 (Sanaz Yashar): For sure, yes.
[26:40] S2 (Sanaz Yashar): First of all, I can tell you that when I started my cyber career, even the name was not cyber.
[26:48] S2 (Sanaz Yashar): It was also not security.
[26:50] S2 (Sanaz Yashar): Uh, I did all my career in cyber in an offensive cyber, what we called under the government, of course, and doing counter-terror.
[26:58] S2 (Sanaz Yashar): But I think it took at least 10 years when the cyber word even used before that, right?
[27:06] S2 (Sanaz Yashar): Before that it was like hacking or interception and these kind of stuff.
[27:13] S2 (Sanaz Yashar): And still when there is a lot in common between I was in microbiology, which which means that you have to understand how actually your or the organism is is mixed of a code.
[27:30] S2 (Sanaz Yashar): The code is according to DNA, the DNA is coding to RNA, the RNA is coding to protein, right?
[27:39] S2 (Sanaz Yashar): And this is how we can describe the life organism.
[27:43] S2 (Sanaz Yashar): And this is what it is also about cyber.
[27:47] S2 (Sanaz Yashar): At the end, there is a lot about the code behind the scene, which different functionality this code can bring on with them.
[27:57] S2 (Sanaz Yashar): Which kind of bugs or an efficiency this code have that you can hack in.
[28:03] S2 (Sanaz Yashar): And at the same time, how this code moving mutations, like from one creature to become another creature.
[28:13] S2 (Sanaz Yashar): There is a lot of different mutations, and the question is like how you can catalyze or block these kind of changes that the code is actually going through.
[28:24] S2 (Sanaz Yashar): I believe as live organism for the biology, there are two main things that I get from it to the cyber.
[28:33] S2 (Sanaz Yashar): First of all, understanding the behind the scene and the code is matters, but also understanding the phenotype and how this code being evaluated and bringing value to the customers, it matters a lot.
[28:52] S2 (Sanaz Yashar): The same like biology looks like when there is a certain functionality in the code and there is a certain bug in the code, you have compensated controls in your body, too, in order to fix it.
[29:07] S2 (Sanaz Yashar): Unfortunately, this is when the stuff starts to distinguish.
[29:15] S2 (Sanaz Yashar): When it comes to software and tools, it doesn't look that it's almost a self-healing platform.
[29:23] S2 (Sanaz Yashar): Like everything, for everything, you need an operator to fix, right?
[29:30] S2 (Sanaz Yashar): Like when you find these inefficiencies in the code, what we call vulnerabilities, at the end, it's not automatically healing.
[29:43] S2 (Sanaz Yashar): And you ask yourself, how our body is so much efficient compared to amazing software and tools when they always need an operator?
[29:56] S2 (Sanaz Yashar): And the biggest pain of cybersecurity when you come from the offensive war to the defensive war, the biggest pain is we don't have enough operators to operate all the different vulnerabilities.
[30:13] S2 (Sanaz Yashar): Like there is so much code and so much vulnerabilities, and with an AI, you write even more code and more vulnerabilities and more attacks surface, but you don't have enough operators in the world that they can actually fix stuff.
[30:33] S2 (Sanaz Yashar): But coming from Iran to Israel, coming from biology and chemistry to the world of cybersecurity, it has been a great perspective and I owe a lot of my career to that, I think.
[30:51] S1 (Yossi Carmazin): So, yeah, so I can tell you definitely not the most conventional path to say the least.
[30:56] S1 (Yossi Carmazin): And I actually also learned biology and chemistry, but only back in high school.
[31:01] S2 (Sanaz Yashar): So, oh, interesting.
[31:04] S2 (Sanaz Yashar): We should do some gathering.
[31:06] S1 (Yossi Carmazin): Yeah, so it's actually a great segue to my next question because you started biology, but what lessons did you learn there that helped shape your approach to cybersecurity?
[31:16] S1 (Yossi Carmazin): And do you see any similarities between these two worlds?
[31:19] S2 (Sanaz Yashar): For sure, yes.
[31:20] S2 (Sanaz Yashar): First of all, I can tell you that when I started my cyber career, even the name was not cyber.
[31:28] S2 (Sanaz Yashar): It was also not security.
[31:30] S2 (Sanaz Yashar): Uh, I did all my career in cyber in an offensive cyber, what we called under the government, of course, and doing counter-terror.
[31:38] S2 (Sanaz Yashar): But I think it took at least 10 years when the cyber word even used before that, right?
[31:46] S2 (Sanaz Yashar): Before that it was like hacking or interception and these kind of stuff.
[31:53] S2 (Sanaz Yashar): And still when there is a lot in common between I was in microbiology, which which means that you have to understand how actually your or the organism is is mixed of a code.
[32:10] S2 (Sanaz Yashar): The code is according to DNA, the DNA is coding to RNA, the RNA is coding to protein, right?
[32:19] S2 (Sanaz Yashar): And this is how we can describe the life organism.
[32:24] S2 (Sanaz Yashar): And this is what it is also about cyber.
[32:28] S2 (Sanaz Yashar): At the end, there is a lot about the code behind the scene, which different functionality this code can bring on with them.
[32:37] S2 (Sanaz Yashar): Which kind of bugs or an efficiency this code have that you can hack in.
[32:43] S2 (Sanaz Yashar): And at the same time, how this code moving mutations, like from one creature to become another creature.
[32:53] S2 (Sanaz Yashar): There is a lot of different mutations, and the question is like how you can catalyze or block these kind of changes that the code is actually going through.
[33:04] S2 (Sanaz Yashar): I believe as live organism for the biology, there are two main things that I get from it to the cyber.
[33:13] S2 (Sanaz Yashar): First of all, understanding the behind the scene and the code is matters, but also understanding the phenotype and how this code being evaluated and bringing value to the customers, it matters a lot.
[33:32] S2 (Sanaz Yashar): The same like biology looks like when there is a certain functionality in the code and there is a certain bug in the code, you have compensated controls in your body, too, in order to fix it.
[33:47] S2 (Sanaz Yashar): Unfortunately, this is when the stuff starts to distinguish.
[33:55] S2 (Sanaz Yashar): When it comes to software and tools, it doesn't look that it's almost a self-healing platform.
[34:03] S2 (Sanaz Yashar): Like everything, for everything, you need an operator to fix, right?
[34:10] S2 (Sanaz Yashar): Like when you find these inefficiencies in the code, what we call vulnerabilities, at the end, it's not automatically healing.
[34:23] S2 (Sanaz Yashar): And you ask yourself, how our body is so much efficient compared to amazing software and tools when they always need an operator?
[34:37] S2 (Sanaz Yashar): And the biggest pain of cybersecurity when you come from the offensive war to the defensive war, the biggest pain is we don't have enough operators to operate all the different vulnerabilities.
[34:53] S2 (Sanaz Yashar): Like there is so much code and so much vulnerabilities, and with an AI, you write even more code and more vulnerabilities and more attacks surface, but you don't have enough operators in the world that they can actually fix stuff.
[35:13] S2 (Sanaz Yashar): But coming from Iran to Israel, coming from biology and chemistry to the world of cybersecurity, it has been a great perspective and I owe a lot of my career to that, I think.
[35:31] S1 (Yossi Carmazin): So, yeah, so I can tell you definitely not the most conventional path to say the least.
[35:36] S1 (Yossi Carmazin): And I actually also learned biology and chemistry, but only back in high school.
[35:41] S2 (Sanaz Yashar): So, oh, interesting.
[35:44] S2 (Sanaz Yashar): We should do some gathering.
[35:46] S1 (Yossi Carmazin): Yeah, so it's actually a great segue to my next question because you started biology, but what lessons did you learn there that helped shape your approach to cybersecurity?
[35:56] S1 (Yossi Carmazin): And do you see any similarities between these two worlds?
[35:59] S2 (Sanaz Yashar): For sure, yes.
[36:00] S2 (Sanaz Yashar): First of all, I can tell you that when I started my cyber career, even the name was not cyber.
[36:08] S2 (Sanaz Yashar): It was also not security.
[36:10] S2 (Sanaz Yashar): Uh, I did all my career in cyber in an offensive cyber, what we called under the government, of course, and doing counter-terror.
[36:18] S2 (Sanaz Yashar): But I think it took at least 10 years when the cyber word even used before that, right?
[36:26] S2 (Sanaz Yashar): Before that it was like hacking or interception and these kind of stuff.
[36:33] S2 (Sanaz Yashar): And still when there is a lot in common between I was in microbiology, which which means that you have to understand how actually your or the organism is is mixed of a code.
[36:50] S2 (Sanaz Yashar): The code is according to DNA, the DNA is coding to RNA, the RNA is coding to protein, right?
[36:59] S2 (Sanaz Yashar): And this is how we can describe the life organism.
[37:03] S2 (Sanaz Yashar): And this is what it is also about cyber.
[37:07] S2 (Sanaz Yashar): At the end, there is a lot about the code behind the scene, which different functionality this code can bring on with them.
[37:17] S2 (Sanaz Yashar): Which kind of bugs or an efficiency this code have that you can hack in.
[37:23] S2 (Sanaz Yashar): And at the same time, how this code moving mutations, like from one creature to become another creature.
[37:33] S2 (Sanaz Yashar): There is a lot of different mutations, and the question is like how you can catalyze or block these kind of changes that the code is actually going through.
[37:44] S2 (Sanaz Yashar): I believe as live organism for the biology, there are two main things that I get from it to the cyber.
[37:53] S2 (Sanaz Yashar): First of all, understanding the behind the scene and the code is matters, but also understanding the phenotype and how this code being evaluated and bringing value to the customers, it matters a lot.
[38:12] S2 (Sanaz Yashar): The same like biology looks like when there is a certain functionality in the code and there is a certain bug in the code, you have compensated controls in your body, too, in order to fix it.
[38:27] S2 (Sanaz Yashar): Unfortunately, this is when the stuff starts to distinguish.
[38:35] S2 (Sanaz Yashar): When it comes to software and tools, it doesn't look that it's almost a self-healing platform.
[38:43] S2 (Sanaz Yashar): Like everything, for everything, you need an operator to fix, right?
[38:50] S2 (Sanaz Yashar): Like when you find these inefficiencies in the code, what we call vulnerabilities, at the end, it's not automatically healing.
[39:03] S2 (Sanaz Yashar): And you ask yourself, how our body is so much efficient compared to amazing software and tools when they always need an operator?
[39:17] S2 (Sanaz Yashar): And the biggest pain of cybersecurity when you come from the offensive war to the defensive war, the biggest pain is we don't have enough operators to operate all the different vulnerabilities.
[39:33] S2 (Sanaz Yashar): Like there is so much code and so much vulnerabilities, and with an AI, you write even more code and more vulnerabilities and more attacks surface, but you don't have enough operators in the world that they can actually fix stuff.
[39:53] S2 (Sanaz Yashar): But coming from Iran to Israel, coming from biology and chemistry to the world of cybersecurity, it has been a great perspective and I owe a lot of my career to that, I think.
[40:11] S1 (Yossi Carmazin): So, yeah, so I can tell you definitely not the most conventional path to say the least.
[40:16] S1 (Yossi Carmazin): And I actually also learned biology and chemistry, but only back in high school.
[40:21] S2 (Sanaz Yashar): So, oh, interesting.
[40:24] S2 (Sanaz Yashar): We should do some gathering.
[40:26] S1 (Yossi Carmazin): Yeah, so it's actually a great segue to my next question because you started biology, but what lessons did you learn there that helped shape your approach to cybersecurity?
[40:36] S1 (Yossi Carmazin): And do you see any similarities between these two worlds?
[40:39] S2 (Sanaz Yashar): For sure, yes.
[40:40] S2 (Sanaz Yashar): First of all, I can tell you that when I started my cyber career, even the name was not cyber.
[40:48] S2 (Sanaz Yashar): It was also not security.
[40:50] S2 (Sanaz Yashar): Uh, I did all my career in cyber in an offensive cyber, what we called under the government, of course, and doing counter-terror.
[40:58] S2 (Sanaz Yashar): But I think it took at least 10 years when the cyber word even used before that, right?
[41:06] S2 (Sanaz Yashar): Before that it was like hacking or interception and these kind of stuff.
[41:13] S2 (Sanaz Yashar): And still when there is a lot in common between I was in microbiology, which which means that you have to understand how actually your or the organism is is mixed of a code.
[41:30] S2 (Sanaz Yashar): The code is according to DNA, the DNA is coding to RNA, the RNA is coding to protein, right?
[41:39] S2 (Sanaz Yashar): And this is how we can describe the life organism.
[41:43] S2 (Sanaz Yashar): And this is what it is also about cyber.
[41:47] S2 (Sanaz Yashar): At the end, there is a lot about the code behind the scene, which different functionality this code can bring on with them.
[41:57] S2 (Sanaz Yashar): Which kind of bugs or an efficiency this code have that you can hack in.
[42:03] S2 (Sanaz Yashar): And at the same time, how this code moving mutations, like from one creature to become another creature.
[42:13] S2 (Sanaz Yashar): There is a lot of different mutations, and the question is like how you can catalyze or block these kind of changes that the code is actually going through.
[42:24] S2 (Sanaz Yashar): I believe as live organism for the biology, there are two main things that I get from it to the cyber.
[42:33] S2 (Sanaz Yashar): First of all, understanding the behind the scene and the code is matters, but also understanding the phenotype and how this code being evaluated and bringing value to the customers, it matters a lot.
[42:52] S2 (Sanaz Yashar): The same like biology looks like when there is a certain functionality in the code and there is a certain bug in the code, you have compensated controls in your body, too, in order to fix it.
[43:07] S2 (Sanaz Yashar): Unfortunately, this is when the stuff starts to distinguish.
[43:15] S2 (Sanaz Yashar): When it comes to software and tools, it doesn't look that it's almost a self-healing platform.
[43:23] S2 (Sanaz Yashar): Like everything, for everything, you need an operator to fix, right?
[43:30] S2 (Sanaz Yashar): Like when you find these inefficiencies in the code, what we call vulnerabilities, at the end, it's not automatically healing.
[43:43] S2 (Sanaz Yashar): And you ask yourself, how our body is so much efficient compared to amazing software and tools when they always need an operator?
[43:56] S2 (Sanaz Yashar): And the biggest pain of cybersecurity when you come from the offensive war to the defensive war, the biggest pain is we don't have enough operators to operate all the different vulnerabilities.

## QUOTES
- "[05:14]" "And the biggest pain of cybersecurity when you come from the offensive war to the defensive war, the biggest pain is we don't have enough operators to operate all the different vulnerabilities." -> why it matters: identifies the central operator shortage in enterprise cybersecurity
- "[06:22]" "I was a part of maybe the best cybersecurity services in the world, I'm not kidding. The name is Mandiant." -> why it matters: highlights her formative operational background at Mandiant
- "[09:19]" "Today, it's like kind of simple, you do scan, right? And then you say, okay, have like, I'm not kidding, like when I say 30 million vulnerabilities, these are the real numbers we are seeing." -> why it matters: exposes the fatigue and volume issue of vulnerability management
- "[10:17]" "So, from threat analysis, we move to the risk analysis and we bubble it up by understanding the threat, but also the layers of the security." -> why it matters: outlines the core methodology behind Zafran's prioritization engine
- "[22:33]" "And I believe the next generation of cybersecurity, it should look more like biology, when it's a self-healing platform..." -> why it matters: shows her visionary alignment of biological concepts with automated security

## BUYING_AND_VENDOR_SIGNALS
[09:19] "Today, it's like kind of simple, you do scan, right? And then you say, okay, have like, I'm not kidding, like when I say 30 million vulnerabilities, these are the real numbers we are seeing." -> illustrates how buyers face overwhelming alert fatigue from traditional scanners.
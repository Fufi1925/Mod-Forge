
def fix_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    new_lines = []
    for line in lines:
        if 'if cat not in cats: cats[cat] = []' in line:
            new_lines.append(line.replace('if cat not in cats: cats[cat] = []', 'if cat not in cats:\n            cats[cat] = []'))
        elif 'if active_count >= 1:  score += 10' in line:
            new_lines.append(line.replace('if active_count >= 1:  score += 10', 'if active_count >= 1:\n        score += 10'))
        elif 'if active_count >= 3:  score += 10' in line:
            new_lines.append(line.replace('if active_count >= 3:  score += 10', 'if active_count >= 3:\n        score += 10'))
        elif 'if active_count >= 6:  score += 10' in line:
            new_lines.append(line.replace('if active_count >= 6:  score += 10', 'if active_count >= 6:\n        score += 10'))
        elif 'if active_count >= 8:  score += 10' in line:
            new_lines.append(line.replace('if active_count >= 8:  score += 10', 'if active_count >= 8:\n        score += 10'))
        elif 'if has_default_log:    score += 8' in line:
            new_lines.append(line.replace('if has_default_log:    score += 8', 'if has_default_log:\n        score += 8'))
        elif 'if log_channels_count >= 3: score += 7' in line:
            new_lines.append(line.replace('if log_channels_count >= 3: score += 7', 'if log_channels_count >= 3:\n        score += 7'))
        elif 'if sec_level >= 1:     score += 8' in line:
            new_lines.append(line.replace('if sec_level >= 1:     score += 8', 'if sec_level >= 1:\n        score += 8'))
        elif 'if sec_level >= 2:     score += 7' in line:
            new_lines.append(line.replace('if sec_level >= 2:     score += 7', 'if sec_level >= 2:\n        score += 7'))
        elif 'if webhook_logging:    score += 5' in line:
            new_lines.append(line.replace('if webhook_logging:    score += 5', 'if webhook_logging:\n        score += 5'))
        elif 'if boost_tier >= 1:    score += 3' in line:
            new_lines.append(line.replace('if boost_tier >= 1:    score += 3', 'if boost_tier >= 1:\n        score += 3'))
        elif 'if err: return err' in line:
            new_lines.append(line.replace('if err: return err', 'if err:\n        return err'))
        elif 'if data["_server_tag"].get("tag"): st["tag"] = data["_server_tag"]["tag"]' in line:
            new_lines.append(line.replace('if data["_server_tag"].get("tag"): st["tag"] = data["_server_tag"]["tag"]', 'if data["_server_tag"].get("tag"):\n            st["tag"] = data["_server_tag"]["tag"]'))
        elif 'if data["value"] not in words: words.append(data["value"])' in line:
            new_lines.append(line.replace('if data["value"] not in words: words.append(data["value"])', 'if data["value"] not in words:\n            words.append(data["value"])'))
        elif 'if 0 <= idx < len(rules): rules.pop(idx)' in line:
            new_lines.append(line.replace('if 0 <= idx < len(rules): rules.pop(idx)', 'if 0 <= idx < len(rules):\n            rules.pop(idx)'))
        elif 'if data["value"] not in domains: domains.append(data["value"])' in line:
            new_lines.append(line.replace('if data["value"] not in domains: domains.append(data["value"])', 'if data["value"] not in domains:\n            domains.append(data["value"])'))
        elif 'if 0 <= idx < len(domains): domains.pop(idx)' in line:
            new_lines.append(line.replace('if 0 <= idx < len(domains): domains.pop(idx)', 'if 0 <= idx < len(domains):\n            domains.pop(idx)'))
        elif 'if 0 <= idx < len(ars): ars.pop(idx)' in line:
            new_lines.append(line.replace('if 0 <= idx < len(ars): ars.pop(idx)', 'if 0 <= idx < len(ars):\n            ars.pop(idx)'))
        elif 'if 0 <= idx < len(ars): ars[idx]["enabled"] = data.get("enabled", True)' in line:
            new_lines.append(line.replace('if 0 <= idx < len(ars): ars[idx]["enabled"] = data.get("enabled", True)', 'if 0 <= idx < len(ars):\n            ars[idx]["enabled"] = data.get("enabled", True)'))
        elif 'if rid not in ar.get("roles",[]): ar.setdefault("roles",[]).append(rid)' in line:
            new_lines.append(line.replace('if rid not in ar.get("roles",[]): ar.setdefault("roles",[]).append(rid)', 'if rid not in ar.get("roles",[]):\n            ar.setdefault("roles",[]).append(rid)'))
        elif 'if rid not in sr: sr.append(rid)' in line:
            new_lines.append(line.replace('if rid not in sr: sr.append(rid)', 'if rid not in sr:\n            sr.append(rid)'))
        elif 'if rid in sr: sr.remove(rid)' in line:
            new_lines.append(line.replace('if rid in sr: sr.remove(rid)', 'if rid in sr:\n            sr.remove(rid)'))
        elif 'for p in params: p["value"] = mcfg.get(p["key"],"")' in line:
            new_lines.append(line.replace('for p in params: p["value"] = mcfg.get(p["key"],"")', 'for p in params:\n                p["value"] = mcfg.get(p["key"],"")'))
        elif 'except Exception: pass' in line:
            new_lines.append(line.replace('except Exception: pass', 'except Exception:\n        pass'))
        elif 'try: wl = bot.db.get_whitelist(int(guild_id))' in line:
            new_lines.append(line.replace('try: wl = bot.db.get_whitelist(int(guild_id))', 'try:\n                wl = bot.db.get_whitelist(int(guild_id))'))
        elif 'cases_count = 0; case_types = {}; top_mods = []; days_labels = []; days_data = []' in line:
            new_lines.append(line.replace('cases_count = 0; case_types = {}; top_mods = []; days_labels = []; days_data = []', 'cases_count = 0\n        case_types = {}\n        top_mods = []\n        days_labels = []\n        days_data = []'))
        elif 'for cs in all_cases: a=cs.get("action","other"); case_types[a]=case_types.get(a,0)+1' in line:
            new_lines.append(line.replace('for cs in all_cases: a=cs.get("action","other"); case_types[a]=case_types.get(a,0)+1', 'for cs in all_cases:\n                    a=cs.get("action","other")\n                    case_types[a]=case_types.get(a,0)+1'))
        elif 'if x["id"] == "1303627964734246944": return (0, "")' in line:
            new_lines.append(line.replace('if x["id"] == "1303627964734246944": return (0, "")', 'if x["id"] == "1303627964734246944":\n                return (0, "")'))
        elif 'if x["id"] == "1491447622442160248": return (1, "")' in line:
            new_lines.append(line.replace('if x["id"] == "1491447622442160248": return (1, "")', 'if x["id"] == "1491447622442160248":\n                return (1, "")'))
        elif 'if x.get("tag") == "ModForge Bot": return (1, "")' in line:
            new_lines.append(line.replace('if x.get("tag") == "ModForge Bot": return (1, "")', 'if x.get("tag") == "ModForge Bot":\n                return (1, "")'))
        elif 'if isinstance(raw,list): activities = [a for a in raw if str(a.get("guild_id",""))==str(guild_id)][:20]' in line:
            new_lines.append(line.replace('if isinstance(raw,list): activities = [a for a in raw if str(a.get("guild_id",""))==str(guild_id)][:20]', 'if isinstance(raw,list):\n            activities = [a for a in raw if str(a.get("guild_id",""))==str(guild_id)][:20]'))
        elif 'if n.get("timestamp"): n["timestamp"] = n["timestamp"].isoformat() + "Z"' in line:
            new_lines.append(line.replace('if n.get("timestamp"): n["timestamp"] = n["timestamp"].isoformat() + "Z"', 'if n.get("timestamp"):\n                n["timestamp"] = n["timestamp"].isoformat() + "Z"'))
        elif 'if c.get("created_at"): c["created_at"] = c["created_at"].isoformat() + "Z"' in line:
            new_lines.append(line.replace('if c.get("created_at"): c["created_at"] = c["created_at"].isoformat() + "Z"', 'if c.get("created_at"):\n                c["created_at"] = c["created_at"].isoformat() + "Z"'))
        elif 'if c.get("timestamp"): c["timestamp"] = c["timestamp"].isoformat() + "Z"' in line:
            new_lines.append(line.replace('if c.get("timestamp"): c["timestamp"] = c["timestamp"].isoformat() + "Z"', 'if c.get("timestamp"):\n                c["timestamp"] = c["timestamp"].isoformat() + "Z"'))
        elif 'if not text: return jsonify({"error": "missing text"}), 400' in line:
            new_lines.append(line.replace('if not text: return jsonify({"error": "missing text"}), 400', 'if not text:\n        return jsonify({"error": "missing text"}), 400'))
        elif 'if entry.reason: mod_info += f"\\nGrund: {entry.reason}"' in line:
            new_lines.append(line.replace('if entry.reason: mod_info += f"\\nGrund: {entry.reason}"', 'if entry.reason:\n                                mod_info += f"\\nGrund: {entry.reason}"'))
        elif 'if age_days < 7: risk += 30' in line:
            new_lines.append(line.replace('if age_days < 7: risk += 30', 'if age_days < 7:\n        risk += 30'))
        elif 'elif age_days < 30: risk += 15' in line:
            new_lines.append(line.replace('elif age_days < 30: risk += 15', 'elif age_days < 30:\n        risk += 15'))
        elif 'if not target.avatar: risk += 10' in line:
            new_lines.append(line.replace('if not target.avatar: risk += 10', 'if not target.avatar:\n        risk += 10'))
        elif 'if warn_count > 0: risk += min(warn_count * 10, 30)' in line:
            new_lines.append(line.replace('if warn_count > 0: risk += min(warn_count * 10, 30)', 'if warn_count > 0:\n        risk += min(warn_count * 10, 30)'))
        elif 'if case_count > 0: risk += min(case_count * 5, 20)' in line:
            new_lines.append(line.replace('if case_count > 0: risk += min(case_count * 5, 20)', 'if case_count > 0:\n        risk += min(case_count * 5, 20)'))
        elif 'if v.mute or v.self_mute: flags.append("🔇 Muted")' in line:
            new_lines.append(line.replace('if v.mute or v.self_mute: flags.append("🔇 Muted")', 'if v.mute or v.self_mute:\n            flags.append("🔇 Muted")'))
        elif 'if v.deaf or v.self_deaf: flags.append("🔇 Deafened")' in line:
            new_lines.append(line.replace('if v.deaf or v.self_deaf: flags.append("🔇 Deafened")', 'if v.deaf or v.self_deaf:\n            flags.append("🔇 Deafened")'))
        elif 'if v.self_stream: flags.append("📺 Streaming")' in line:
            new_lines.append(line.replace('if v.self_stream: flags.append("📺 Streaming")', 'if v.self_stream:\n            flags.append("📺 Streaming")'))
        elif 'if v.self_video: flags.append("📹 Kamera")' in line:
            new_lines.append(line.replace('if v.self_video: flags.append("📹 Kamera")', 'if v.self_video:\n            flags.append("📹 Kamera")'))
        elif 'for cc in raw: cc["timestamp"] = str(cc.get("timestamp",""))[:19]' in line:
            new_lines.append(line.replace('for cc in raw: cc["timestamp"] = str(cc.get("timestamp",""))[:19]', 'for cc in raw:\n                    cc["timestamp"] = str(cc.get("timestamp",""))[:19]'))
        else:
            new_lines.append(line)
            
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(new_lines)

fix_file('web/routes.py')
fix_file('bot/bot.py')

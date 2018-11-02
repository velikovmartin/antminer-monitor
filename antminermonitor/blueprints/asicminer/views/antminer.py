import re
import time
from datetime import timedelta
import telegram_send

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, url_for)
from flask_login import login_required
from sqlalchemy.exc import IntegrityError

from antminermonitor.blueprints.asicminer.models import Miner, MinerModel
from antminermonitor.extensions import db
from lib.pycgminer import get_pools, get_stats, get_summary
from lib.util_hashrate import update_unit_and_value

antminer = Blueprint('antminer', __name__, template_folder='../templates')


@antminer.route('/')
@login_required
def miners():
    # Init variables
    start = time.clock()
    miners = Miner.query.all()
    models = MinerModel.query.order_by(MinerModel.model).all()
    active_miners = []
    inactive_miners = []
    workers = {}
    miner_chips = {}
    temperatures = {}
    fans = {}
    hash_rates = {}
    hw_error_rates = {}
    uptimes = {}
    total_hash_rate_per_model = {
        "L3+": {
            "value": 0,
            "unit": "MH/s"
        },
        "S7": {
            "value": 0,
            "unit": "GH/s"
        },
        "S9": {
            "value": 0,
            "unit": "GH/s"
        },
        "S9_broken": {
            "value": 0,
            "unit": "GH/s"
        },
        "D3": {
            "value": 0,
            "unit": "MH/s"
        },
        "T9": {
            "value": 0,
            "unit": "GH/s"
        },
        "T9+": {
            "value": 0,
            "unit": "GH/s"
        },
        "A3": {
            "value": 0,
            "unit": "GH/s"
        },
        "L3": {
            "value": 0,
            "unit": "MH/s"
        },
        "R4": {
            "value": 0,
            "unit": "TH/s"
        },
        "V9": {
            "value": 0,
            "unit": "GH/s"
        },
        "X3": {
            "value": 0,
            "unit": "KH/s"
        },
        "Z9 mini": {
            "value": 0,
            "unit": "KSol/s"
        },
        "Z9 bigi": {
            "value": 0,
            "unit": "KSol/s"
        },
        "E3": {
            "value": 0,
            "unit": "MH/s"
        },
    }

    errors = False
    miner_errors = {}

    for miner in miners:
        miner_stats = get_stats(miner.ip)
        # if miner not accessible
        if miner_stats['STATUS'][0]['STATUS'] == 'error':
            errors = True
            inactive_miners.append(miner)
        else:
            # Get worker name
            miner_pools = get_pools(miner.ip)
            active_pool = [
                pool for pool in miner_pools['POOLS'] if pool['Stratum Active']
            ]
            try:
                worker = active_pool[0]['User']
            except KeyError as k:
                worker = ""
            except ValueError as v:
                worker = ""
            # Get miner's ASIC chips
            asic_chains = [
                miner_stats['STATS'][1][chain]
                for chain in miner_stats['STATS'][1].keys()
                if "chain_acs" in chain
            ]
            # count number of working chips
            o = [str(o).count('o') for o in asic_chains]
            Os = sum(o)
            # count number of defective chips
            X = [str(x).count('x') for x in asic_chains]
            C = [str(x).count('C') for x in asic_chains]
            B = [str(x).count('B') for x in asic_chains]
            Xs = sum(X)
            Bs = sum(B)
            Cs = sum(C)
            # get number of in-active chips
            _dash_chips = [str(x).count('-') for x in asic_chains]
            _dash_chips = sum(_dash_chips)
            # Get total number of chips according to miner's model
            # convert miner.model.chips to int list and sum
            chips_list = [int(y) for y in str(miner.model.chips).split(',')]
            total_chips = sum(chips_list)
            # Get the temperatures of the miner according to miner's model
            temps = [
                int(miner_stats['STATS'][1][temp]) for temp in sorted(
                    miner_stats['STATS'][1].keys(), key=lambda x: str(x))
                if re.search(miner.model.temp_keys + '[0-9]', temp)
                if miner_stats['STATS'][1][temp] != 0
            ]
            # Get fan speeds
            fan_speeds = [
                miner_stats['STATS'][1][fan] for fan in sorted(
                    miner_stats['STATS'][1].keys(), key=lambda x: str(x))
                if re.search("fan" + '[0-9]', fan)
                if miner_stats['STATS'][1][fan] != 0
            ]
            # Get GH/S 5s
            try:
                ghs5s = float(str(miner_stats['STATS'][1]['GHS 5s']))
            except ValueError as v:
                ghs5s = 0
            except KeyError as k:
                miner_summary = get_summary(miner.ip)
                ghs5s = float(str(miner_summary['SUMAMRY'][0]['GHS 5s']))
            # Get HW Errors
            try:
                hw_error_rate = miner_stats['STATS'][1]['Device Hardware%']
            except KeyError as k:
                # Probably the miner is an Antminer E3
                miner_summary = get_summary(miner.ip)
                hw_error_rate = miner_summary['SUMMARY'][0]['Device Hardware%']
            except ValueError as v:
                hw_error_rate = 0
            # Get uptime
            uptime = timedelta(seconds=miner_stats['STATS'][1]['Elapsed'])
            #
            workers.update({miner.ip: worker})
            miner_chips.update({
                miner.ip: {
                    'status': {
                        'Os': Os,
                        'Xs': Xs,
                        '-': _dash_chips
                    },
                    'total': total_chips,
                }
            })
            temperatures.update({miner.ip: temps})
            fans.update({miner.ip: {"speeds": fan_speeds}})
            value, unit = update_unit_and_value(
                ghs5s, total_hash_rate_per_model[miner.model.model]['unit'])
            hash_rates.update({miner.ip: "{:3.2f} {}".format(value, unit)})
            hw_error_rates.update({miner.ip: hw_error_rate})
            uptimes.update({miner.ip: uptime})
            total_hash_rate_per_model[miner.model.model]["value"] += ghs5s
            active_miners.append(miner)

            # Flash error messages
            if Xs > 0:
                error_message = ("[WARNING] '{}' chips are defective on "
                                 "miner '{}'.").format(Xs, miner.ip)
                current_app.logger.warning(error_message)
                flash(error_message, "warning")
                errors = True
                miner_errors.update({miner.ip: error_message})
                telegram_send.send([error_message])
            if Os + Xs < total_chips:
                error_message = (
                    "[ERROR] ASIC chips are missing from miner "
                    "'{}'. Your Antminer '{}' has '{}/{} chips'.").format(
                        miner.ip, miner.model.model, Os + Xs, total_chips)
                current_app.logger.error(error_message)
                flash(error_message, "error")
                errors = True
                miner_errors.update({miner.ip: error_message})
                telegram_send.send([error_message])
            if Bs > 0:
                # flash an info message. Probably the E3 is still warming up
                # error_message = (
                #    "[INFO] Miner '{}' is still warming up").format(miner.ip)
                # current_app.logger.error(error_message)
                # flash(error_message, "info")
                pass
            if Cs > 0:
                # flask an info message. Probably the E3 is still warming up
                # error_message = (
                #    "[INFO] Miner '{}' is still warming up").format(miner.ip)
                # current_app.logger.error(error_message)
                # flash(error_message, "info")
                pass
            if temps:
                if max(temps) >= 85 and max(temps) < 90:
                    error_message = ("[WARNING] High temperatures on "
                                     "miner '{}'.").format(miner.ip)
                    current_app.logger.warning(error_message)
                    flash(error_message, "warning")
                elif max(temps) >= 90:
                    error_message = ("[WARNING] High temperatures on "
                                     "miner '{}'.").format(miner.ip)
                    current_app.logger.warning(error_message)
                    flash(error_message, "warning")
                    telegram_send.send([error_message])
            if not temps:
                temperatures.update({miner.ip: 0})
                error_message = ("[ERROR] Could not retrieve temperatures "
                                 "from miner '{}'.").format(miner.ip)
                current_app.logger.warning(error_message)
                flash(error_message, "error")
            if ghs5s == 0:
                error_message = ("[ERROR] Miner ghs5s ('{}') is bellow normal '{}'.").format(ghs5s, miner.ip) 
                current_app.logger.warning(error_message)
                flash(error_message, "error") 
                errors = True 
                miner_errors.update({miner.ip: error_message})
                telegram_send.send([error_message])
            elif ghs5s < 11000 and miner.model.model == 'S9':
                error_message = ("[Warning] Miner ghs5s ('{}') is bellow normal '{}'.").format(ghs5s, miner.ip) 
                current_app.logger.warning(error_message)
                miner_errors.update({miner.ip: error_message})
                flash(error_message, "warning")
                telegram_send.send([error_message])
            elif ghs5s < 35 and miner.model.model == 'Z9 bigi':
                error_message = ("[Warning] Miner ghs5s ('{}') is bellow normal '{}'.").format(ghs5s, miner.ip) 
                current_app.logger.warning(error_message)
                miner_errors.update({miner.ip: error_message})
                flash(error_message, "warning")
                telegram_send.send([error_message])
            # if  len(active_miners) < 38:
            #     error_message = ("[Warning] Some miners are not working Exact:('{}').").format(38 - len(active_miners)) 
            #     current_app.logger.warning(error_message)
            #     flash(error_message, "error") 
            #     errors = True 
            #     miner_errors.update({miner.ip: error_message})
            #     telegram_send.send([error_message])

    # Flash success/info message
    if not miners:
        error_message = ("[INFO] No miners added yet. "
                         "Please add miners using the above form.")
        current_app.logger.info(error_message)
        flash(error_message, "info")
    elif not errors:
        error_message = ("[INFO] All miners are operating normal. "
                         "No errors found.")
        current_app.logger.info(error_message)
        flash(error_message, "info")

    # flash("[INFO] Check chips on your miner", "info")
    # flash("[SUCCESS] Miner added successfully", "success")
    # flash("[WARNING] Check temperatures on your miner", "warning")
    # flash("[ERROR] Check board(s) on your miner", "error")

    # Convert the total_hash_rate_per_model into a data structure that the
    # template can consume.
    total_hash_rate_per_model_temp = {}
    for key in total_hash_rate_per_model:
        value, unit = update_unit_and_value(
            total_hash_rate_per_model[key]["value"],
            total_hash_rate_per_model[key]["unit"])
        if value > 0:
            total_hash_rate_per_model_temp[key] = "{:3.2f} {}".format(
                value, unit)

    end = time.clock()
    loading_time = end - start
    return render_template(
        'asicminer/home.html',
        version=current_app.config['__VERSION__'],
        models=models,
        active_miners=active_miners,
        inactive_miners=inactive_miners,
        workers=workers,
        miner_chips=miner_chips,
        temperatures=temperatures,
        fans=fans,
        hash_rates=hash_rates,
        hw_error_rates=hw_error_rates,
        uptimes=uptimes,
        total_hash_rate_per_model=total_hash_rate_per_model_temp,
        loading_time=loading_time,
        miner_errors=miner_errors,
    )


@antminer.route('/add', methods=['POST'])
@login_required
def add_miner():
    miner_ip = request.form['ip']
    miner_model_id = request.form.get('model_id')
    miner_remarks = request.form['remarks']

    # exists = Miner.query.filter_by(ip="").first()
    # if exists:
    #    return "IP Address already added"

    try:
        miner = Miner(
            ip=miner_ip, model_id=miner_model_id, remarks=miner_remarks)
        db.session.add(miner)
        db.session.commit()
        flash("Miner with IP Address {} added successfully".format(miner.ip),
              "success")
    except IntegrityError:
        db.session.rollback()
        flash("IP Address {} already added".format(miner_ip), "error")

    return redirect(url_for('antminer.miners'))


@antminer.route('/delete/<id>')
@login_required
def delete_miner(id):
    miner = Miner.query.filter_by(id=int(id)).first()
    db.session.delete(miner)
    db.session.commit()
    return redirect(url_for('antminer.miners'))

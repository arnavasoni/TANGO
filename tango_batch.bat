@echo off
REM -------------------------------
REM Batch file to run tango scripts inside virtual environment
REM -------------------------------

REM Path to your virtual environment
set VENV_PATH=C:\CODING\TANGO\final_attempt\tango_venv

REM Activate the venv
call "%VENV_PATH%\Scripts\activate.bat"

REM ----------------------------------
REM Script Paths
REM ----------------------------------

REM Processing script (AWB + Invoice extraction)
set SCRIPT_PROCESS=C:\CODING\TANGO\watch_dog\tango_match.py

REM Deduplication scripts
set SCRIPT_AWB_DEDUP=C:\CODING\TANGO\watch_dog\one_time_cleans\otc_awb.py
set SCRIPT_INVOICE_DEDUP=C:\CODING\TANGO\watch_dog\one_time_cleans\otc_invoice.py

REM Excel writer
set SCRIPT_EXCEL=C:\CODING\TANGO\watch_dog\tango_excel_writer.py

REM ----------------------------------
REM Step 1: Deduplicate AWB Output
REM ----------------------------------
echo Removing duplicate AWB entries...
python "%SCRIPT_AWB_DEDUP%"
echo AWB deduplication completed.

timeout /t 10 /nobreak >nul

REM ----------------------------------
REM Step 2: Deduplicate Invoice Output
REM ----------------------------------
echo Removing duplicate invoice entries...
python "%SCRIPT_INVOICE_DEDUP%"
echo Invoice deduplication completed.

timeout /t 10 /nobreak >nul

REM ----------------------------------
REM Step 3: Run tango_match.py
REM ----------------------------------
echo Running tango_match.py...
python "%SCRIPT_PROCESS%"
echo tango_match.py completed.

timeout /t 10 /nobreak >nul

REM ----------------------------------
REM Step 4: Write to Excel
REM ----------------------------------
echo Writing to Excel...
python "%SCRIPT_EXCEL%"
echo Excel writing completed.

echo TANGO pipeline execution completed!

pause

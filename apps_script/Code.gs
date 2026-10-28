/**
 * Portfolio <-> Google Sheet bridge.
 * Deploy: Extensions > Apps Script > paste this file > Project Settings > Script properties:
 *   SECRET = <any long random string>   (same value as SHEETS_SECRET in .env)
 * Deploy > New deployment > Web app > Execute as: Me, Who has access: Anyone > copy the URL to SHEETS_WEBAPP_URL.
 * The secret is the access control, so keep it private.
 */
function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    if (body.secret !== PropertiesService.getScriptProperties().getProperty('SECRET')) return out_({ok: false, error: 'bad secret'});
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    Object.keys(body.sheets).forEach(function (name) {
      var grid = body.sheets[name];
      var sh = ss.getSheetByName(name) || ss.insertSheet(name);
      sh.clear();
      if (grid.length && grid[0].length) {
        sh.getRange(1, 1, grid.length, grid[0].length).setValues(grid);
        sh.getRange(1, 1, 1, grid[0].length).setFontWeight('bold');
        sh.setFrozenRows(1);
      }
    });
    return out_({ok: true});
  } catch (err) { return out_({ok: false, error: String(err)}); }
}

function doGet(e) {
  if (e.parameter.secret !== PropertiesService.getScriptProperties().getProperty('SECRET')) return out_({ok: false, error: 'bad secret'});
  var sheets = {};
  SpreadsheetApp.getActiveSpreadsheet().getSheets().forEach(function (sh) {
    var v = sh.getDataRange().getValues();
    sheets[sh.getName()] = (v.length === 1 && v[0].length === 1 && v[0][0] === '') ? [] : v;
  });
  return out_({ok: true, sheets: sheets});
}

function out_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}

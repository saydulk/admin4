# The Admin4 Project
# (c) 2013-2014 Andreas Pflug
#
# Licensed under the Apache License, 
# see LICENSE.TXT for conditions of usage


from wh import xlt, AcceleratorHelper, Menu
import wx.aui
import adm

from _pgsql import pgQuery
from _sqlgrid import SqlFrame, SqlEditGrid
from _sqledit import SqlEditor
from Table import Table


class ColSpec:
  def __init__(self, row):
    self.category=row['typcategory']
    self.notNull=row['attnotnull']
    self.length=-1
    self.precision=-1
    self.pgtype=row['formatted']
    self.typoid=row['atttypid']
    fmt=self.pgtype.split('(')
    _typ=fmt[0]
    if len(fmt) > 1:
      p=fmt[1][:-1].split(',')
      self.length=int(p[0])
      if len(p) > 1:
        self.precision=int(p[1])

  def IsNumeric(self):
    return self.category == 'N'

   
  def GetClass(self):
    # http://www.postgresql.org/docs/9.3/static/catalog-pg-type.html#CATALOG-TYPCATEGORY-TABLE
    if self.category == 'B':  # bool
      return bool
    elif self.category == 'N':  # numeric
      return int
    elif self.category == 'S':
      return unicode
    return unicode 


class TableSpecs:
  def __init__(self, node):
    self.tabName=node.NameSql()
    self.cursor=node.GetCursor()
    self.serverVersion= node.GetServer().version
    
    row=self.cursor.ExecuteRow("""
      SELECT c.oid, relhasoids
        FROM pg_class c
       WHERE oid=oid(regclass('%s'))
    """ % self.tabName)
    if not row:
      raise Exception(xlt("No such table: %s") % self.tabName)
    self.oid=row['oid']
    self.hasoids = row['relhasoids']
    
    self.constraints = self.cursor.ExecuteDictList(Table.getConstraintQuery(self.oid))

    self.colSpecs={}
    self.colNames=[]
    set=self.cursor.ExecuteSet("""
        SELECT attname, attnotnull, atttypid, atttypmod, t.typcategory, CASE WHEN typbasetype >0 THEN format_type(typbasetype,typtypmod) ELSE format_type(atttypid, atttypmod) END as formatted
         FROM pg_attribute a
         JOIN pg_type t on t.oid=atttypid
        WHERE attrelid=%d
          AND attnum>0 and not attisdropped
        ORDER BY attnum
    """ % self.oid)
    for row in set:
      attname=row['attname']
      self.colNames.append(attname)
      self.colSpecs[attname]=ColSpec(row)

    self.primaryConstraint=None
    if self.hasoids:
      self.keyCols=[]
    else:
      for c in self.constraints:
        if c.get('indisprimary'):
          self.primaryConstraint=c;
          break;
      if not self.primaryConstraint:
        for c in self.constraints:
          if c.get('isunique'):
            self.primaryConstraint=c;
            break;
      if self.primaryConstraint:
        self.keyCols=self.primaryConstraint.get('colnames')


class TextDropTarget(wx.TextDropTarget):
  def __init__(self, lb):
    wx.TextDropTarget.__init__(self)
    self.lb=lb
  
  def OnDropText(self, x, y, text):
    target=self.lb.HitTest((x, y))
    if target >= 0:
      source=int(text)
      if target == source:
        return
      if hasattr(self.lb, 'IsChecked'):
        chk=self.lb.IsChecked(source)
      text=self.lb.GetString(source)
      self.lb.Delete(source)
      self.lb.Insert(text, target)
      if hasattr(self.lb, 'IsChecked'):
        self.lb.Check(target, chk)
  
  
class FilterPanel(adm.NotebookPanel):
  def __init__(self, dlg, notebook):
    adm.NotebookPanel.__init__(self, dlg, notebook)
    self.Bind("LimitCheck", self.OnLimitCheck)
    self.Bind("FilterCheck", self.OnFilterCheck)
    self.Bind("FilterValidate", self.OnFilterValidate)
    self.Bind("FilterValue", self.OnFilterValueChanged)
#    self['SortCols'].Bind(wx.EVT_LISTBOX_DCLICK, self.OnDclickSort)
#    self['DisplayCols'].Bind(wx.EVT_MOTION, self.OnBeginDrag)
    self['SortCols'].Bind(wx.EVT_MOTION, self.domove)
#    self['SortCols'].Bind(wx.EVT_LEFT_DOWN, self.OnBeginDrag)
    self.OnLimitCheck()
    self.OnFilterCheck()
    self.valid=True
    self.dialog=dlg


  def domove(self, evt):
    print "MOVE", evt.GetPosition(), evt.EventObject
    

  def OnBeginDrag(self, evt):
    print "DOWN", evt.GetPosition()
#    return
    if evt.GetPosition().x < 30:
      evt.Skip()
      return
    lb=evt.EventObject
    i=lb.HitTest(evt.GetPosition())
    if i >= 0:
      lb.SetDropTarget(TextDropTarget(lb))
      data=wx.PyTextDataObject(str(i))
      ds=wx.DropSource(lb)
      ds.SetData(data)
      ds.DoDragDrop(False)
      lb.SetDropTarget(None)
    
  def OnDclickSort(self, evt):
    colname=self['SortCols'].GetString(evt.Selection)
    if colname.endswith(" DESC"):
      colname=colname[:-5]
    else:
      colname = colname+" DESC"
    self['SortCols'].SetString(evt.Selection, colname)
  
  def OnLimitCheck(self, evt=None):
    self.EnableControls("LimitValue", self.LimitCheck)

  def OnFilterCheck(self, evt=None):
    self.EnableControls("FilterValue FilterValidate", self.FilterCheck)
    self.OnFilterValueChanged(evt)

  def OnFilterValueChanged(self, evt):
    self.valid=not self.FilterCheck
    self.dialog.updateMenu()
  
  def OnFilterValidate(self, evt):
    self.valid=False
    
    sql="EXPLAIN " + self.GetQuery()
    self.tableSpecs.cursor.ExecuteSet(sql)  # will throw exception if invalid

    self.dialog.SetStatus(xlt("Filter expression valid"))
    self.valid=True
    self.dialog.updateMenu()

  def Go(self, tableSpecs):
    self.tableSpecs=tableSpecs
    dc=self['DisplayCols']
    sc=self['SortCols']
    
    for colName in self.tableSpecs.colNames:
      i=dc.Append(colName)
      dc.Check(i, True)
      i=sc.Append(colName)
      if colName in self.tableSpecs.keyCols:
        sc.Check(i, True)
      
  def GetQuery(self):
    query=pgQuery(self.tableSpecs.tabName)
    for colName in self['DisplayCols'].GetCheckedStrings():
      query.AddCol(colName)
    for colName in self['SortCols'].GetCheckedStrings():
      query.AddOrder(colName)
    if self.FilterCheck:
      query.AddWhere(self.FilterValue.strip())
    
    sql= query.SelectQueryString()
    if self.LimitCheck:
      sql += "\n LIMIT %d" % self.LimitValue
    return sql

class DataFrame(SqlFrame):
  def __init__(self, parentWin, node):
    self.tableSpecs=TableSpecs(node)
    self.worker=None
    SqlFrame.__init__(self, parentWin, xlt("Data Tool"), "SqlData")

    toolbar=self.GetToolBar()

    toolbar.Add(self.OnRefresh, xlt("Refresh"), "refresh")
    toolbar.Add(self.OnCancelRefresh, xlt("Cancel refresh"), "query_cancel")
    toolbar.Add(self.OnShowFilter, xlt("Show filter window"), "filter")
    toolbar.AddSeparator()
    toolbar.Add(self.OnCopy, xlt("Copy"), "clip_copy")
    toolbar.Add(self.OnCut, xlt("Cut"), "clip_cut")
    toolbar.Add(self.OnPaste, xlt("Paste"), "clip_paste")
    toolbar.Add(self.OnUndo, xlt("Undo"), "edit_undo")

    menubar=wx.MenuBar()
    self.datamenu=menu=Menu()
    self.AddMenu(menu, xlt("Refresh"), xlt("Refresh data"), self.OnRefresh)
    self.AddMenu(menu, xlt("Cancel"), xlt("Cancel refresh"), self.OnCancelRefresh)
    menu.AppendSeparator()
    self.AddMenu(menu, xlt("Show filter"), xlt("Show filter window"), self.OnShowFilter)
    menubar.Append(menu, xlt("&Data"))
    
    self.editmenu=menu=Menu()
    self.AddMenu(menu, xlt("Cu&t"), xlt("Cut selected data to clipboard"), self.OnCut)
    self.AddMenu(menu, xlt("&Copy"), xlt("Copy selected data to clipboard"), self.OnCopy)
    self.AddMenu(menu, xlt("&Paste"), xlt("Paste data from clipboard"), self.OnPaste)
    self.AddMenu(menu, xlt("&Undo"), xlt("discard last editing"), self.OnUndo)
    menubar.Append(menu, xlt("&Edit"))

    self.EnableMenu(self.datamenu, self.OnCancelRefresh, False)
    self.SetMenuBar(menubar)

    toolbar.Realize()

    ah=AcceleratorHelper(self)
    ah.Add(wx.ACCEL_CTRL, 'X', self.OnCut)
    ah.Add(wx.ACCEL_CTRL, 'C', self.OnCopy)
    ah.Add(wx.ACCEL_CTRL, 'V', self.OnPaste)
    ah.Add(wx.ACCEL_NORMAL,wx.WXK_F5, self.OnRefresh)
    ah.Add(wx.ACCEL_ALT,wx.WXK_PAUSE, self.OnCancelRefresh)
    ah.Realize()
    
    self.notebook=wx.Notebook(self)
    self.notebook.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.OnCheck)
    self.filter=FilterPanel(self, self.notebook)
    self.notebook.AddPage(self.filter, xlt("Filter, Order, Limit"))
    self.editor=SqlEditor(self.notebook)
    self.editor.SetAcceleratorTable(ah.GetTable())
    self.notebook.AddPage(self.editor, xlt("Manual SQL"))
    
    self.manager.AddPane(self.notebook, wx.aui.AuiPaneInfo().Top().PaneBorder().Resizable().MinSize((200,200)).BestSize((400,200)).CloseButton(True) \
                          .Name("filter").Caption(xlt("SQL query parameter")))


    self.output = SqlEditGrid(self, self.tableSpecs)
    self.manager.AddPane(self.output, wx.aui.AuiPaneInfo().Center().MinSize((200,100)).BestSize((400,200)).CloseButton(False) \
                          .Name("Edit Data").Caption(xlt("Edit Data")).CaptionVisible(False))

    self.restorePerspective()
    self.updateMenu()
    self.filter.Go(self.tableSpecs)
    self.editor.SetText("/*\n%s\n*/\n\n%s" % (xlt("Caution: may show unpredicted behaviour.\nDon't mess with table and column names!"), self.filter.GetQuery()))

    
  def OnShowFilter(self, evt):
    paneInfo=self.manager.GetPane("filter")
    paneInfo.Show(not paneInfo.IsShown())
    self.manager.Update()    
    

  def OnCheck(self, evt):
    if evt.GetSelection():
      self.editor.Show()
    self.updateMenu(evt.GetSelection())
      
  def updateMenu(self, sel=None):
    if sel == None:
      sel=self.notebook.GetSelection()
    if sel:
      ok=True
    else:
      ok=self.filter.valid
      if not self.filter.FilterCheck:
        self.SetStatus()
        
    self.EnableMenu(self.datamenu, self.OnRefresh, ok)
    

  def executeQuery(self, sql):
    self.output.SetEmpty()
    
    self.EnableMenu(self.datamenu, self.OnRefresh, False)
    self.EnableMenu(self.datamenu, self.OnCancelRefresh, True)
    
    self.startTime=wx.GetLocalTimeMillis();
    self.worker=worker=self.tableSpecs.cursor.ExecuteAsync(sql)
    worker.start()
    
    self.SetStatus(xlt("Query is running."));
    self.SetStatusText("", self.STATUSPOS_ROWS)

    self.pollWorker()

    self.EnableMenu(self.datamenu, self.OnCancelRefresh, False)
    self.EnableMenu(self.datamenu, self.OnRefresh, True)
  
    txt=xlt("%d rows")
    if not self.notebook.GetSelection() and self.filter.LimitCheck:
      txt += " LIMIT"
    self.SetStatusText(txt % worker.GetRowcount(), self.STATUSPOS_ROWS)

    if worker.cancelled:
      self.SetStatus(xlt("Cancelled."));
      self.output.SetData(worker.GetResult())
    elif worker.error:
      errmsg=worker.error.error.decode('utf8')
      errlines=errmsg.splitlines()
      self.SetStatus(errlines[0]);
    else:
      self.SetStatus(xlt("OK."));
      
      self.output.SetData(worker.GetResult())
      

 
  def OnRefresh(self, evt=None):
    if self.notebook.GetSelection():
      sql=self.editor.GetSelectedText()
      if not sql:
        sql=self.editor.GetText()
      if not sql.strip():
        return
    else:
      sql=self.filter.GetQuery()
    self.executeQuery(sql)
  
  def OnCancelRefresh(self, evt):
    self.EnableMenu(self.datamenu, self.OnCancelRefresh, False)
    if self.worker:
      self.worker.Cancel()
  
  def OnUndo(self, evt):
    self.output.RevertEdit()
    

  def OnClose(self, evt):
    self.OnCancelRefresh(None)
    if self.output.table and self.output.table.currentRow:
      dlg=wx.MessageDialog(self, xlt("Data is changed but not written.\nSave now?"), xlt("Unsaved data"), 
                           wx.YES_NO|wx.CANCEL|wx.CANCEL_DEFAULT|wx.ICON_EXCLAMATION)
      rc=dlg.ShowModal()
      if rc == wx.ID_CANCEL:
        return 
      elif rc == wx.ID_YES:
        self.output.table.Commit()
    adm.config.storeWindowPositions(self)
    self.Destroy()

class DataTool:
  name=xlt("Data Tool")
  help=xlt("Show and modify data")
  toolbitmap='SqlData'
  knownClasses=['Table', 'View']

  @staticmethod
  def CheckAvailableOn(node):
    return node.__class__.__name__ in DataTool.knownClasses

  @staticmethod
  def CheckEnabled(node):
    return node.__class__.__name__ in DataTool.knownClasses

  @staticmethod
  def OnExecute(parentWin, node):
    frame=DataFrame(parentWin, node)
    frame.Show()
    wx.SafeYield()
    frame.OnRefresh()

  
nodeinfo=[]
menuinfo=[{"class": DataTool, "sort": 30 } ]

